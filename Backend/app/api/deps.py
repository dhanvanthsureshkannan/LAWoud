"""FastAPI dependency providers. Services are constructed once at startup
(see app.main's lifespan) and stored on app.state; these just fetch them
back out for route handlers, so nothing above the API layer imports FastAPI."""

from fastapi import Request

from app.services.ai.ai_service import AIService
from app.services.knowledge_service import KnowledgeService
from app.services.web_search_service import WebSearchService


def get_ai_service(request: Request) -> AIService:
    return request.app.state.ai_service


def get_knowledge_service(request: Request) -> KnowledgeService:
    return request.app.state.knowledge_service


def get_web_search_service(request: Request) -> WebSearchService:
    return request.app.state.web_search_service
