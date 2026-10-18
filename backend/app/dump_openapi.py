"""Prints the API description (OpenAPI JSON). The web app's types are generated from it:
`npm run gen:api` in frontend/."""

import json

from app.web import create_app

if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1))
