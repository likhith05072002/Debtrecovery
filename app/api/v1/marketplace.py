"""Marketplace template endpoints — browse, install, and publish templates."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.onboarding import MarketplaceTemplate
from app.models.database.user import User

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class TemplateResponse(BaseModel):
    id: str
    category: str
    name: str
    description: str | None
    config: dict
    author_org_id: str | None
    downloads: int
    rating: float
    is_public: bool
    created_at: str


class TemplateCreateRequest(BaseModel):
    category: str = Field(pattern="^(script|campaign|compliance_pack)$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    config: dict
    is_public: bool = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TemplateResponse])
async def browse_templates(
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace templates. Public endpoint."""
    query = (
        select(MarketplaceTemplate)
        .where(MarketplaceTemplate.is_public == True)
        .order_by(MarketplaceTemplate.downloads.desc())
    )
    if category:
        query = query.where(MarketplaceTemplate.category == category)
    if search:
        query = query.where(MarketplaceTemplate.name.ilike(f"%{search}%"))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)

    return [_serialize_template(t) for t in result.scalars().all()]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a single template by ID."""
    template = await db.get(MarketplaceTemplate, template_id)
    if not template or not template.is_public:
        raise HTTPException(status_code=404, detail="Template not found")
    return _serialize_template(template)


@router.post("/{template_id}/install")
async def install_template(
    template_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Install a template into the current organization."""
    template = await db.get(MarketplaceTemplate, template_id)
    if not template or not template.is_public:
        raise HTTPException(status_code=404, detail="Template not found")

    # Increment download count
    template.downloads += 1

    # Return the config for the frontend to apply
    return {
        "template_id": str(template.id),
        "category": template.category,
        "name": template.name,
        "config": template.config,
        "message": f"Template '{template.name}' installed successfully",
    }


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def publish_template(
    body: TemplateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publish a new template to the marketplace. Requires Growth+ plan."""
    template = MarketplaceTemplate(
        category=body.category,
        name=body.name,
        description=body.description,
        config=body.config,
        author_org_id=current_user.organization_id,
        is_public=body.is_public,
    )
    db.add(template)
    await db.flush()

    return _serialize_template(template)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_template(t: MarketplaceTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=str(t.id),
        category=t.category,
        name=t.name,
        description=t.description,
        config=t.config,
        author_org_id=str(t.author_org_id) if t.author_org_id else None,
        downloads=t.downloads,
        rating=float(t.rating),
        is_public=t.is_public,
        created_at=t.created_at.isoformat(),
    )
