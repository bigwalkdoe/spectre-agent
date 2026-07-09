# API Client Template

Generic typed async REST API client built on `httpx` and `pydantic`.

## Usage

```python
from __future__ import annotations

from pydantic import BaseModel
from src.client import APIClient, APIError
from src.models import BaseResponse


class User(BaseModel):
    id: int
    name: str
    email: str


class CreateUser(BaseModel):
    name: str
    email: str


async def main() -> None:
    async with APIClient[CreateUser, BaseResponse[User]](
        base_url="https://api.example.com",
        api_key="sk-...",
    ) as client:
        # GET
        users = await client.get("/users", BaseResponse[User])
        print(users.data)

        # POST
        new_user = await client.post(
            "/users",
            BaseResponse[User],
            json_body=CreateUser(name="Alice", email="alice@example.com"),
        )
        print(new_user.data)

        # PATCH
        updated = await client.patch(
            "/users/1",
            BaseResponse[User],
            json_body={"name": "Alice Updated"},
        )
        print(updated.data)

        # DELETE
        deleted = await client.delete("/users/1", BaseResponse[User])
        print(deleted.status)

        # Error handling
        try:
            await client.get("/users/99999", BaseResponse[User])
        except APIError as exc:
            print(f"{exc.status_code}: {exc.detail.message if exc.detail else 'unknown'}")
```

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy src/
pytest
```
