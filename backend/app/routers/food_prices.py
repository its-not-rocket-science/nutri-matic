from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Food, FoodPrice, User

router = APIRouter(prefix="/api/food-prices", tags=["food-prices"])


def _price_out(price: FoodPrice, food_name: str) -> schemas.FoodPriceOut:
    return schemas.FoodPriceOut(
        id=price.id,
        food_id=price.food_id,
        food_name=food_name,
        package_price=price.package_price,
        package_quantity_g=price.package_quantity_g,
        price_per_100g=price.package_price / price.package_quantity_g * 100,
    )


@router.get("", response_model=list[schemas.FoodPriceOut])
def list_prices(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prices = db.query(FoodPrice).filter(FoodPrice.user_id == current_user.id).all()
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_([p.food_id for p in prices])).all()}
    out = [_price_out(p, foods_by_id[p.food_id].name) for p in prices]
    out.sort(key=lambda p: p.food_name)
    return out


@router.put("/{food_id}", response_model=schemas.FoodPriceOut)
def set_price(
    food_id: int,
    body: schemas.FoodPriceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    food = db.get(Food, food_id)
    if food is None:
        raise HTTPException(status_code=422, detail=f"Unknown food id: {food_id}")

    price = db.query(FoodPrice).filter(FoodPrice.user_id == current_user.id, FoodPrice.food_id == food_id).one_or_none()
    if price is None:
        price = FoodPrice(user_id=current_user.id, food_id=food_id)
        db.add(price)
    price.package_price = body.package_price
    price.package_quantity_g = body.package_quantity_g
    db.commit()
    db.refresh(price)

    return _price_out(price, food.name)


@router.delete("/{food_id}", status_code=204)
def delete_price(food_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    price = db.query(FoodPrice).filter(FoodPrice.user_id == current_user.id, FoodPrice.food_id == food_id).one_or_none()
    if price is None:
        raise HTTPException(status_code=404, detail="No price set for that food")
    db.delete(price)
    db.commit()
