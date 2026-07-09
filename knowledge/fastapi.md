# FastAPI Patterns

## App Factory

```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="Service Name", version="0.1.0")
    # register middleware, routes, lifespan
    return app
```

## Dependency Injection

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session

@app.get("/items")
async def list_items(db: AsyncSession = Depends(get_db)):
    ...
```

## Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_db()
    yield
    # shutdown
    await close_db()

app = FastAPI(lifespan=lifespan)
```
