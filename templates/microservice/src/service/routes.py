from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from service.database import get_session
from service.models import Item
from service.schemas import ItemCreate, ItemResponse, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemResponse])
async def list_items(
    session: AsyncSession = Depends(get_session),
) -> list[ItemResponse]:
    result = await session.execute(select(Item).order_by(Item.created_at))
    items = result.scalars().all()
    return [ItemResponse.model_validate(item) for item in items]


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ItemResponse:
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item not found")
    return ItemResponse.model_validate(item)


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ItemCreate,
    session: AsyncSession = Depends(get_session),
) -> ItemResponse:
    item = Item(name=payload.name, description=payload.description)
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return ItemResponse.model_validate(item)


@router.patch("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: UUID,
    payload: ItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> ItemResponse:
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item not found")
    if payload.name is not None:
        item.name = payload.name
    if payload.description is not None:
        item.description = payload.description
    await session.flush()
    await session.refresh(item)
    return ItemResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item not found")
    await session.delete(item)
