from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user, get_owned_profile
from ..database import get_db
from ..models import DiaryEntry, DiaryMealTemplate, DiaryMealTemplateItem, Food, Profile, Recipe, User
from ..schemas import Meal

router = APIRouter(prefix="/api/diary-meal-templates", tags=["diary-meal-templates"])


def _get_owned_template(template_id: int, profile: Profile, db: Session) -> DiaryMealTemplate:
    template = db.get(DiaryMealTemplate, template_id)
    if template is None or template.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Diary meal template not found")
    return template


@router.post("", response_model=schemas.DiaryMealTemplateOut, status_code=201)
def create_template(
    body: schemas.DiaryMealTemplateCreate,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    source_entries = (
        db.query(DiaryEntry)
        .filter(
            DiaryEntry.profile_id == profile.id,
            DiaryEntry.entry_date == body.entry_date,
            DiaryEntry.meal == body.meal,
        )
        .all()
    )
    if not source_entries:
        raise HTTPException(status_code=422, detail="No diary entries logged for that date and meal")

    template = DiaryMealTemplate(user_id=current_user.id, profile_id=profile.id, name=body.name)
    db.add(template)
    db.flush()

    for entry in source_entries:
        db.add(
            DiaryMealTemplateItem(
                template_id=template.id,
                food_id=entry.food_id,
                quantity_g=entry.quantity_g,
                recipe_id=entry.recipe_id,
                quantity_servings=entry.quantity_servings,
            )
        )
    db.commit()

    return schemas.DiaryMealTemplateOut(id=template.id, name=template.name, item_count=len(source_entries))


@router.get("", response_model=list[schemas.DiaryMealTemplateOut])
def list_templates(profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    templates = db.query(DiaryMealTemplate).filter(DiaryMealTemplate.profile_id == profile.id).all()
    counts: dict[int, int] = {}
    for item in db.query(DiaryMealTemplateItem).filter(
        DiaryMealTemplateItem.template_id.in_([t.id for t in templates])
    ).all():
        counts[item.template_id] = counts.get(item.template_id, 0) + 1

    return [
        schemas.DiaryMealTemplateOut(id=t.id, name=t.name, item_count=counts.get(t.id, 0))
        for t in sorted(templates, key=lambda t: t.name)
    ]


@router.get("/{template_id}", response_model=schemas.DiaryMealTemplateDetailOut)
def get_template(template_id: int, profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    template = _get_owned_template(template_id, profile, db)
    items = db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.template_id == template.id).all()

    food_ids = {i.food_id for i in items if i.food_id is not None}
    recipe_ids = {i.recipe_id for i in items if i.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    items_out = [
        schemas.DiaryMealTemplateItemOut(
            food_id=i.food_id,
            food_name=foods_by_id[i.food_id].name if i.food_id else None,
            quantity_g=i.quantity_g,
            recipe_id=i.recipe_id,
            recipe_name=recipes_by_id[i.recipe_id].name if i.recipe_id else None,
            quantity_servings=i.quantity_servings,
        )
        for i in items
    ]

    return schemas.DiaryMealTemplateDetailOut(id=template.id, name=template.name, items=items_out)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    template = _get_owned_template(template_id, profile, db)
    db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.template_id == template.id).delete()
    db.delete(template)
    db.commit()


@router.post("/{template_id}/apply", response_model=list[schemas.DiaryEntryOut], status_code=201)
def apply_template(
    template_id: int,
    entry_date: date,
    meal: Meal,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    template = _get_owned_template(template_id, profile, db)
    items = db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.template_id == template.id).all()

    created: list[DiaryEntry] = []
    for item in items:
        # a recipe in the template might since have been deleted, or (if it were ever transferred)
        # no longer belong to this user — skip rather than fail the whole apply for one stale item
        if item.recipe_id is not None:
            recipe = db.get(Recipe, item.recipe_id)
            if recipe is None or recipe.user_id != current_user.id:
                continue
        if item.food_id is not None and db.get(Food, item.food_id) is None:
            continue

        entry = DiaryEntry(
            user_id=current_user.id,
            profile_id=profile.id,
            entry_date=entry_date,
            meal=meal,
            food_id=item.food_id,
            quantity_g=item.quantity_g,
            recipe_id=item.recipe_id,
            quantity_servings=item.quantity_servings,
        )
        db.add(entry)
        created.append(entry)

    db.commit()
    for entry in created:
        db.refresh(entry)

    food_ids = {e.food_id for e in created if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in created if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    return [
        schemas.DiaryEntryOut(
            id=e.id,
            entry_date=e.entry_date,
            meal=e.meal,
            food_id=e.food_id,
            food_name=foods_by_id[e.food_id].name if e.food_id else None,
            quantity_g=e.quantity_g,
            recipe_id=e.recipe_id,
            recipe_name=recipes_by_id[e.recipe_id].name if e.recipe_id else None,
            quantity_servings=e.quantity_servings,
        )
        for e in created
    ]
