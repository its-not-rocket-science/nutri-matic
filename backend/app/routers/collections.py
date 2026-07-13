from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Collection, CollectionRecipe, User
from .recipes import _get_visible_recipe, _recipe_out

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _get_owned_collection(collection_id: int, current_user: User, db: Session) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None or collection.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _recipe_count(collection_id: int, db: Session) -> int:
    return db.query(CollectionRecipe).filter(CollectionRecipe.collection_id == collection_id).count()


@router.post("", response_model=schemas.CollectionOut, status_code=201)
def create_collection(
    body: schemas.CollectionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    collection = Collection(user_id=current_user.id, name=body.name)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return schemas.CollectionOut(id=collection.id, name=collection.name, recipe_count=0)


@router.get("", response_model=list[schemas.CollectionOut])
def list_collections(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    collections = db.query(Collection).filter(Collection.user_id == current_user.id).order_by(Collection.name).all()
    return [
        schemas.CollectionOut(id=c.id, name=c.name, recipe_count=_recipe_count(c.id, db)) for c in collections
    ]


@router.get("/{collection_id}", response_model=schemas.CollectionDetailOut)
def get_collection(
    collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    collection = _get_owned_collection(collection_id, current_user, db)
    links = db.query(CollectionRecipe).filter(CollectionRecipe.collection_id == collection.id).all()
    recipes = []
    for link in links:
        try:
            recipe = _get_visible_recipe(link.recipe_id, current_user, db)
        except HTTPException:
            # the recipe's no longer visible (e.g. a share was revoked) —
            # skip it rather than 404ing the whole collection
            continue
        recipes.append(_recipe_out(recipe, db, current_user))
    return schemas.CollectionDetailOut(id=collection.id, name=collection.name, recipes=recipes)


@router.delete("/{collection_id}", status_code=204)
def delete_collection(
    collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    collection = _get_owned_collection(collection_id, current_user, db)
    db.query(CollectionRecipe).filter(CollectionRecipe.collection_id == collection.id).delete()
    db.delete(collection)
    db.commit()


@router.post("/{collection_id}/recipes", response_model=schemas.CollectionDetailOut, status_code=201)
def add_recipe_to_collection(
    collection_id: int,
    body: schemas.CollectionRecipeAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = _get_owned_collection(collection_id, current_user, db)
    # must be visible to the caller (their own, or shared with them) —
    # filing a recipe into a personal collection doesn't clone it, so it
    # only makes sense for recipes the caller can actually see
    _get_visible_recipe(body.recipe_id, current_user, db)

    exists = db.query(CollectionRecipe).filter(
        CollectionRecipe.collection_id == collection.id, CollectionRecipe.recipe_id == body.recipe_id
    ).one_or_none()
    if exists is None:
        db.add(CollectionRecipe(collection_id=collection.id, recipe_id=body.recipe_id))
        db.commit()
    return get_collection(collection_id, current_user, db)


@router.delete("/{collection_id}/recipes/{recipe_id}", response_model=schemas.CollectionDetailOut)
def remove_recipe_from_collection(
    collection_id: int,
    recipe_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = _get_owned_collection(collection_id, current_user, db)
    db.query(CollectionRecipe).filter(
        CollectionRecipe.collection_id == collection.id, CollectionRecipe.recipe_id == recipe_id
    ).delete()
    db.commit()
    return get_collection(collection_id, current_user, db)
