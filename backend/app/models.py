from sqlalchemy import Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Food(Base):
    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    protein_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)

    # mg indispensable amino acid per g protein; keys match reference_patterns.AMINO_ACIDS.
    # Individual values may be null where source data doesn't cover that amino acid.
    amino_acids: Mapped[dict] = mapped_column(JSON, nullable=False)

    # per-amino-acid true ileal digestibility coefficients (0-1), for DIAAS
    digestibility_diaas: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # provenance of digestibility_diaas: "measured" (published coefficient for this
    # specific food) or "estimated" (broad food-category fallback), null if unset
    digestibility_diaas_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # single overall crude protein digestibility coefficient (0-1), for PDCAAS
    digestibility_pdcaas: Mapped[float | None] = mapped_column(Float, nullable=True)

    # USDA FoodData Central provenance, null for manually-entered foods
    fdc_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True, index=True)
    data_type: Mapped[str | None] = mapped_column(String, nullable=True)
