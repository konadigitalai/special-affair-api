from dataclasses import dataclass
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.shopping_copilot.policy import prohibited_intent
from app.ai.shopping_copilot.retrieval import retrieve_products
from app.ai.shopping_copilot.schemas import ProductEvidence


@dataclass
class CopilotResult:
    answer: str
    intent: str
    products: list[ProductEvidence]
    disclaimer: str | None = None


class CopilotState(TypedDict, total=False):
    message: str
    session: AsyncSession
    blocked: str | None
    rows: list[Any]
    result: CopilotResult


async def classify(state: CopilotState) -> dict[str, object]:
    return {"blocked": prohibited_intent(state["message"])}


def route_after_classification(state: CopilotState) -> str:
    return "blocked" if state.get("blocked") else "retrieve"


async def blocked_response(_: CopilotState) -> dict[str, object]:
    return {"result": CopilotResult(
            answer="I can explain options, but I cannot perform that protected commerce action. Please use the authorized backend workflow.",
            intent="restricted_action",
            products=[],
            disclaimer="AI suggestions never override backend authorization or commerce state.",
        )}


async def retrieve(state: CopilotState) -> dict[str, object]:
    return {"rows": await retrieve_products(state["session"], state["message"])}


async def compose(state: CopilotState) -> dict[str, object]:
    rows = state["rows"]
    products = [ProductEvidence(slug=p.slug, name=p.name, description=p.description, variant_id=v.id, variant=v.name, colour=v.colour, material=v.material, price_minor=v.price_minor, currency=v.currency) for p, v in rows]
    if not products:
        result = CopilotResult("I couldn't find a published product matching those requirements. Try changing the colour, material, or budget.", "product_search", [])
        return {"result": result}
    names = ", ".join(f"{item.name} — {item.variant}" for item in products[:3])
    return {"result": CopilotResult(f"I found {len(products)} matching option(s): {names}. Prices and product facts come from the live catalogue.", "product_search", products)}


def build_graph() -> Any:
    graph = StateGraph(CopilotState)
    graph.add_node("classify", cast(Any, classify))
    graph.add_node("blocked", cast(Any, blocked_response))
    graph.add_node("retrieve", cast(Any, retrieve))
    graph.add_node("compose", cast(Any, compose))
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", route_after_classification, {"blocked": "blocked", "retrieve": "retrieve"})
    graph.add_edge("blocked", END)
    graph.add_edge("retrieve", "compose")
    graph.add_edge("compose", END)
    return graph.compile()


async def run_workflow(session: AsyncSession, message: str) -> CopilotResult:
    state = await build_graph().ainvoke({"session": session, "message": message})
    return state["result"]
