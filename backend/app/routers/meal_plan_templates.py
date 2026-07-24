from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user, get_owned_profile
from ..database import get_db
from ..models import Food, MealPlanEntry, MealPlanTemplate, MealPlanTemplateEntry, Profile, Recipe, User
from ..recipe_access import is_recipe_visible

router = APIRouter(prefix="/api/meal-plan-templates", tags=["meal-plan-templates"])


def _get_owned_template(template_id: int, profile: Profile, db: Session) -> MealPlanTemplate:
    template = db.get(MealPlanTemplate, template_id)
    if template is None or template.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Meal plan template not found")
    return template


@router.post("", response_model=schemas.MealPlanTemplateOut, status_code=201)
def create_template(
    body: schemas.MealPlanTemplateCreate,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    if (body.end_date - body.start_date).days != 6:
        raise HTTPException(status_code=422, detail="A template snapshots exactly one week (start_date to start_date+6)")

    source_entries = (
        db.query(MealPlanEntry)
        .filter(
            MealPlanEntry.profile_id == profile.id,
            MealPlanEntry.plan_date >= body.start_date,
            MealPlanEntry.plan_date <= body.end_date,
        )
        .all()
    )

    template = MealPlanTemplate(user_id=current_user.id, profile_id=profile.id, name=body.name)
    db.add(template)
    db.flush()

    for entry in source_entries:
        db.add(
            MealPlanTemplateEntry(
                template_id=template.id,
                day_offset=(entry.plan_date - body.start_date).days,
                meal=entry.meal,
                food_id=entry.food_id,
                quantity_g=entry.quantity_g,
                recipe_id=entry.recipe_id,
                quantity_servings=entry.quantity_servings,
            )
        )
    db.commit()

    return schemas.MealPlanTemplateOut(id=template.id, name=template.name, entry_count=len(source_entries))


@router.get("", response_model=list[schemas.MealPlanTemplateOut])
def list_templates(profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    templates = db.query(MealPlanTemplate).filter(MealPlanTemplate.profile_id == profile.id).all()
    counts: dict[int, int] = {}
    for entry in db.query(MealPlanTemplateEntry).filter(
        MealPlanTemplateEntry.template_id.in_([t.id for t in templates])
    ).all():
        counts[entry.template_id] = counts.get(entry.template_id, 0) + 1

    return [
        schemas.MealPlanTemplateOut(id=t.id, name=t.name, entry_count=counts.get(t.id, 0))
        for t in sorted(templates, key=lambda t: t.name)
    ]


@router.get("/{template_id}", response_model=schemas.MealPlanTemplateDetailOut)
def get_template(template_id: int, profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    template = _get_owned_template(template_id, profile, db)
    entries = db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.template_id == template.id).all()

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    entries_out = [
        schemas.MealPlanTemplateEntryOut(
            day_offset=e.day_offset,
            meal=e.meal,
            food_id=e.food_id,
            food_name=foods_by_id[e.food_id].name if e.food_id else None,
            quantity_g=e.quantity_g,
            recipe_id=e.recipe_id,
            recipe_name=recipes_by_id[e.recipe_id].name if e.recipe_id else None,
            quantity_servings=e.quantity_servings,
        )
        for e in sorted(entries, key=lambda e: (e.day_offset, e.meal))
    ]

    return schemas.MealPlanTemplateDetailOut(id=template.id, name=template.name, entries=entries_out)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    template = _get_owned_template(template_id, profile, db)
    db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.template_id == template.id).delete()
    db.delete(template)
    db.commit()


@router.post("/{template_id}/apply", response_model=list[schemas.MealPlanEntryOut], status_code=201)
def apply_template(
    template_id: int,
    start_date: date,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    template = _get_owned_template(template_id, profile, db)
    template_entries = db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.template_id == template.id).all()

    created: list[MealPlanEntry] = []
    for template_entry in template_entries:
        # a recipe in the template might since have been deleted, made
        # private, or unshared — skip rather than fail the whole apply for
        # one stale entry. Visibility (owner/shared/public), not outright
        # ownership — same bug class hardening prompt 6 fixed in
        # diary.py/meal_plan.py's own create paths.
        if template_entry.recipe_id is not None:
            recipe = db.get(Recipe, template_entry.recipe_id)
            if recipe is None or not is_recipe_visible(recipe, current_user, db):
                continue
        if template_entry.food_id is not None and db.get(Food, template_entry.food_id) is None:
            continue

        entry = MealPlanEntry(
            user_id=current_user.id,
            profile_id=profile.id,
            plan_date=start_date + timedelta(days=template_entry.day_offset),
            meal=template_entry.meal,
            food_id=template_entry.food_id,
            quantity_g=template_entry.quantity_g,
            recipe_id=template_entry.recipe_id,
            quantity_servings=template_entry.quantity_servings,
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
        schemas.MealPlanEntryOut(
            id=e.id,
            plan_date=e.plan_date,
            meal=e.meal,
            food_id=e.food_id,
            food_name=foods_by_id[e.food_id].name if e.food_id else None,
            quantity_g=e.quantity_g,
            recipe_id=e.recipe_id,
            recipe_name=recipes_by_id[e.recipe_id].name if e.recipe_id else None,
            quantity_servings=e.quantity_servings,
            updated_at=e.updated_at,
        )
        for e in created
    ]
