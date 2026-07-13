# API Documentation with OpenAPI/Swagger

## Steps

1. Set up FastAPI with OpenAPI:
   - FastAPI auto-generates OpenAPI schema
   - Access at /docs (Swagger UI) and /redoc (ReDoc)
   - Configure application metadata (title, version, description)

2. Add comprehensive route documentation:
   - Add docstrings to each route function
   - Include parameter descriptions
   - Document return types and response codes
   - Add example requests/responses

3. Define Pydantic models for schemas:
   - Use Pydantic models for request/response bodies
   - Add Field descriptions and examples
   - Use Config for schema customization
   - Document validation rules

4. Add response models:
   - Specify response_model in route decorators
   - Create separate response models for different codes
   - Use response_class for non-JSON responses
   - Document all possible response codes

5. Add tags for organization:
   - Group related endpoints with tags
   - Create tag metadata with descriptions
   - Use tags for navigation in Swagger UI

6. Add security schemes:
   - Define security schemes in OpenAPI config
   - Add security requirements to routes
   - Document authentication requirements
   - Include example auth headers

7. Add examples and sample data:
   - Include example values in Pydantic models
   - Add example parameter values
   - Document common use cases
   - Provide example requests for each endpoint

8. Generate client SDKs:
   - Use openapi-generator for client libraries
   - Generate TypeScript, Python, Java clients
   - Include in CI/CD pipeline
   - Publish to package registry

9. Version the API:
   - Include version in URL path (/v1/)
   - Document breaking changes
   - Maintain multiple versions if needed
   - Add deprecation notices

10. Validate OpenAPI spec:
    - Use spectral or openapi-spec-validator
    - Check for missing documentation
    - Validate against OpenAPI 3.0+ spec
    - Include in CI/CD pipeline

## FastAPI Example

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="User API",
    description="User management API",
    version="1.0.0",
    tags_metadata=[
        {"name": "users", "description": "User operations"},
    ]
)

class UserCreate(BaseModel):
    email: str = Field(..., description="User email address", example="user@example.com")
    username: str = Field(..., description="Username", example="johndoe")
    password: str = Field(..., description="Password (min 8 chars)", min_length=8)

@app.post(
    "/users/",
    response_model=UserResponse,
    status_code=201,
    tags=["users"],
    summary="Create a new user",
    description="Create a new user account with email and password"
)
async def create_user(user: UserCreate):
    """
    Create a new user.
    
    - **email**: User's email address (must be unique)
    - **username**: Desired username (must be unique)
    - **password**: Password (min 8 characters)
    """
    return user
```
