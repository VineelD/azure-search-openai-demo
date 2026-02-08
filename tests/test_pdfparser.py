import io
import logging
import pathlib
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from azure.core.credentials import AzureKeyCredential

from prepdocslib.figureprocessor import (
    FigureProcessor,
    MediaDescriptionStrategy,
    build_figure_markup,
    process_page_image,
)
from prepdocslib.page import ImageOnPage

from .mocks import MockAzureCredential

TEST_DATA_DIR = pathlib.Path(__file__).parent / "test-data"


@pytest.fixture
def sample_image():
    """Fixture for a sample ImageOnPage object used across multiple tests."""
    return ImageOnPage(
        bytes=b"fake",
        bbox=(0, 0, 100, 100),
        page_num=1,
        figure_id="fig_1",
        placeholder='<figure id="fig_1"></figure>',
        filename="test.png",
    )


@pytest.mark.asyncio
async def test_figure_processor_openai_requires_client():
    figure_processor = FigureProcessor(strategy=MediaDescriptionStrategy.OPENAI)

    with pytest.raises(ValueError, match="requires both a client and a model name"):
        await figure_processor.describe(b"bytes")


@pytest.mark.asyncio
async def test_figure_processor_openai_describe(monkeypatch):
    figure_processor = FigureProcessor(
        strategy=MediaDescriptionStrategy.OPENAI,
        openai_client=Mock(),
        openai_model="gpt-4o",
        openai_deployment="gpt-4o",
    )

    describer = AsyncMock()
    describer.describe_image.return_value = "Pie chart"

    async def fake_get_media_describer(self):
        return describer

    monkeypatch.setattr(FigureProcessor, "get_media_describer", fake_get_media_describer)

    result = await figure_processor.describe(b"bytes")

    assert result == "Pie chart"
    describer.describe_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_figure_processor_content_understanding_initializes_once(monkeypatch):
    figure_processor = FigureProcessor(
        strategy=MediaDescriptionStrategy.CONTENTUNDERSTANDING,
        credential=MockAzureCredential(),
        content_understanding_endpoint="https://example.com",
    )

    class FakeDescriber:
        def __init__(self, endpoint, credential):
            self.endpoint = endpoint
            self.credential = credential
            self.create_analyzer = AsyncMock()
            self.describe_image = AsyncMock(return_value="A diagram")

    monkeypatch.setattr("prepdocslib.figureprocessor.ContentUnderstandingDescriber", FakeDescriber)

    result_first = await figure_processor.describe(b"image")
    assert result_first == "A diagram"
    describer_instance = figure_processor.media_describer  # type: ignore[attr-defined]
    assert isinstance(describer_instance, FakeDescriber)
    describer_instance.create_analyzer.assert_awaited_once()

    result_second = await figure_processor.describe(b"image")
    assert result_second == "A diagram"
    assert describer_instance.create_analyzer.await_count == 1


@pytest.mark.asyncio
async def test_figure_processor_none_strategy_returns_none():
    figure_processor = FigureProcessor(strategy=MediaDescriptionStrategy.NONE)

    describer = await figure_processor.get_media_describer()
    assert describer is None

    result = await figure_processor.describe(b"bytes")
    assert result is None


@pytest.mark.asyncio
async def test_figure_processor_content_understanding_missing_endpoint():
    figure_processor = FigureProcessor(
        strategy=MediaDescriptionStrategy.CONTENTUNDERSTANDING,
        credential=MockAzureCredential(),
    )

    with pytest.raises(ValueError, match="Content Understanding strategy requires an endpoint"):
        await figure_processor.get_media_describer()


@pytest.mark.asyncio
async def test_figure_processor_content_understanding_missing_credential():
    figure_processor = FigureProcessor(
        strategy=MediaDescriptionStrategy.CONTENTUNDERSTANDING,
        content_understanding_endpoint="https://example.com",
    )

    with pytest.raises(ValueError, match="Content Understanding strategy requires a credential"):
        await figure_processor.get_media_describer()


@pytest.mark.asyncio
async def test_figure_processor_content_understanding_key_credential():
    figure_processor = FigureProcessor(
        strategy=MediaDescriptionStrategy.CONTENTUNDERSTANDING,
        credential=AzureKeyCredential("fake_key"),
        content_understanding_endpoint="https://example.com",
    )

    with pytest.raises(ValueError, match="Content Understanding does not support key credentials"):
        await figure_processor.get_media_describer()


@pytest.mark.asyncio
async def test_figure_processor_openai_returns_describer(monkeypatch):
    mock_client = Mock()
    figure_processor = FigureProcessor(
        strategy=MediaDescriptionStrategy.OPENAI,
        openai_client=mock_client,
        openai_model="gpt-4o",
        openai_deployment="gpt-4o-deployment",
    )

    describer = await figure_processor.get_media_describer()
    assert describer is not None
    assert figure_processor.media_describer is describer

    # Second call should return the same instance
    describer2 = await figure_processor.get_media_describer()
    assert describer2 is describer


@pytest.mark.asyncio
async def test_figure_processor_unknown_strategy(caplog):
    # Create a processor with an invalid strategy by patching the enum
    figure_processor = FigureProcessor(strategy=MediaDescriptionStrategy.NONE)
    # Override the strategy to an unknown value
    figure_processor.strategy = "unknown_strategy"  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING):
        describer = await figure_processor.get_media_describer()

    assert describer is None
    assert "Unknown media description strategy" in caplog.text


@pytest.mark.asyncio
async def test_figure_processor_mark_content_understanding_ready():
    figure_processor = FigureProcessor(strategy=MediaDescriptionStrategy.NONE)

    assert not figure_processor.content_understanding_ready
    figure_processor.mark_content_understanding_ready()
    assert figure_processor.content_understanding_ready


@pytest.mark.asyncio
async def test_build_figure_markup_without_description(sample_image):
    sample_image.title = "Sample Figure"

    result = build_figure_markup(sample_image, description=None)
    assert result == "<figure><figcaption>fig_1 Sample Figure</figcaption></figure>"


@pytest.mark.asyncio
async def test_process_page_image_without_blob_manager(sample_image):
    with pytest.raises(ValueError, match="BlobManager must be provided"):
        await process_page_image(
            image=sample_image,
            document_filename="test.pdf",
            blob_manager=None,
            image_embeddings_client=None,
        )


@pytest.mark.asyncio
async def test_process_page_image_without_figure_processor(sample_image):

    blob_manager = AsyncMock()
    blob_manager.upload_document_image = AsyncMock(return_value="https://example.com/image.png")

    result = await process_page_image(
        image=sample_image,
        document_filename="test.pdf",
        blob_manager=blob_manager,
        image_embeddings_client=None,
        figure_processor=None,
    )

    assert result.description is None
    assert result.url == "https://example.com/image.png"
    blob_manager.upload_document_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_page_image_sets_description(sample_image):

    blob_manager = AsyncMock()
    blob_manager.upload_document_image = AsyncMock(return_value="https://example.com/image.png")

    figure_processor = AsyncMock()
    figure_processor.describe = AsyncMock(return_value="A bar chart")

    result = await process_page_image(
        image=sample_image,
        document_filename="test.pdf",
        blob_manager=blob_manager,
        image_embeddings_client=None,
        figure_processor=figure_processor,
    )

    assert result.description == "A bar chart"
    figure_processor.describe.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_page_image_skips_upload_if_url_exists(sample_image):

    sample_image.url = "https://existing.com/image.png"

    blob_manager = AsyncMock()
    blob_manager.upload_document_image = AsyncMock()

    result = await process_page_image(
        image=sample_image,
        document_filename="test.pdf",
        blob_manager=blob_manager,
        image_embeddings_client=None,
    )

    assert result.url == "https://existing.com/image.png"
    blob_manager.upload_document_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_page_image_with_embeddings(sample_image):

    blob_manager = AsyncMock()
    blob_manager.upload_document_image = AsyncMock(return_value="https://example.com/image.png")

    image_embeddings = AsyncMock()
    image_embeddings.create_embedding_for_image = AsyncMock(return_value=[0.1, 0.2, 0.3])

    result = await process_page_image(
        image=sample_image,
        document_filename="test.pdf",
        blob_manager=blob_manager,
        image_embeddings_client=image_embeddings,
    )

    assert result.embedding == [0.1, 0.2, 0.3]
    image_embeddings.create_embedding_for_image.assert_awaited_once()


def test_image_on_page_from_skill_payload_without_bytes():
    """Test ImageOnPage.from_skill_payload when bytes_base64 is not provided."""
    payload = {
        "filename": "test.png",
        "figure_id": "fig_1",
        "page_num": "1",
        "bbox": [0, 0, 100, 100],
        "document_file_name": "test.pdf",
    }

    image, doc_filename = ImageOnPage.from_skill_payload(payload)

    assert image.bytes == b""
    assert image.filename == "test.png"
    assert image.figure_id == "fig_1"
    assert image.page_num == 1
    assert image.bbox == (0, 0, 100, 100)
    assert doc_filename == "test.pdf"


def test_image_on_page_from_skill_payload_invalid_page_num():
    """Test ImageOnPage.from_skill_payload with invalid page_num."""
    payload = {
        "filename": "test.png",
        "figure_id": "fig_1",
        "page_num": "invalid",
        "bbox": [0, 0, 100, 100],
    }

    image, _ = ImageOnPage.from_skill_payload(payload)

    assert image.page_num == 0


def test_image_on_page_from_skill_payload_invalid_bbox():
    """Test ImageOnPage.from_skill_payload with invalid bbox."""
    payload = {
        "filename": "test.png",
        "figure_id": "fig_1",
        "page_num": 1,
        "bbox": [0, 0, 100],  # Only 3 elements
    }

    image, _ = ImageOnPage.from_skill_payload(payload)

    assert image.bbox == (0, 0, 0, 0)
