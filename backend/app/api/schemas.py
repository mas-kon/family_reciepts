"""Response shapes shared by several routers. The web app's TypeScript types are generated
from them (see frontend/package.json, `npm run gen:api`)."""

from pydantic import BaseModel


class Ok(BaseModel):
    ok: bool = True
