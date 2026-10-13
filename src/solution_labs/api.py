from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .beauty import Beauty
from .common import ConflictError


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BeautyStart(Input):
    scenario: Literal["clean", "bad_batch", "duplicate", "currency"] = "clean"


class BeautyQuestion(Input):
    question: str = Field(min_length=1, max_length=300)
    metric: (
        Literal[
            "net_revenue", "margin_pct", "discount_pct", "cash_collected", "receivables", "overdue"
        ]
        | None
    ) = None
    market: Literal["all", "US", "GB", "CA"] = "all"


def router(root: Path) -> APIRouter:
    routes = APIRouter(prefix="/api/labs", tags=["Independent solution demonstrations"])
    beauty = Beauty(root)

    def identity(value: str | None, allowed: set[str]) -> str:
        if value not in allowed:
            raise HTTPException(401, "Select a valid simulated lab identity")
        return value

    def call(function: Any, *args: Any) -> dict[str, Any]:
        try:
            return cast(dict[str, Any], function(*args))
        except ConflictError as error:
            raise HTTPException(409, str(error)) from error
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @routes.post("/beauty/runs")
    def start_beauty(
        body: BeautyStart, x_demo_identity: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        return call(
            beauty.create, identity(x_demo_identity, {"finance", "commercial"}), body.scenario
        )

    @routes.get("/beauty/runs/{key}")
    def load_beauty(
        key: str, x_demo_identity: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        return call(beauty.snapshot, key, identity(x_demo_identity, {"finance", "commercial"}))

    @routes.post("/beauty/runs/{key}/pipeline")
    def beauty_pipeline(
        key: str, body: BeautyStart, x_demo_identity: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        return call(
            beauty.pipeline,
            key,
            identity(x_demo_identity, {"finance", "commercial"}),
            body.scenario,
        )

    @routes.post("/beauty/runs/{key}/questions")
    def beauty_question(
        key: str, body: BeautyQuestion, x_demo_identity: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        return call(
            beauty.ask,
            key,
            identity(x_demo_identity, {"finance", "commercial"}),
            body.question,
            body.metric,
            body.market,
        )

    return routes
