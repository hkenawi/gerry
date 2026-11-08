"""
Behavior tests for the composition root that assembles the application.
"""

from httpx import AsyncClient, ASGITransport

from backend.application.settings import Settings
from backend.application.composition import build_app


class FakeModel:
    """
    Stand-in model that fails the test if anything tries to call it.
    """

    def __getattr__(self, name: str) -> object:
        """
        Fail loudly if any code path tries to use the model.
        """
        raise AssertionError(f"Model was used unexpectedly: {name}")


async def test_built_app_serves_requests_using_the_injected_model() -> None:
    """
    The app is assembled from injected parts and never builds a real client.
    """
    fake_model = FakeModel()
    settings = Settings(model_name="fake-model", api_key="not-a-real-key")

    app = build_app(settings, fake_model)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert app.state.model is fake_model
