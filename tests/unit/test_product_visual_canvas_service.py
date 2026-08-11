from io import BytesIO

from PIL import Image

from agent.services.product_visual_canvas_service import (
    STANDARD_VISUAL_CANVAS_SIZE,
    normalize_image_to_standard_canvas,
    standardize_image_file_to_canvas,
)


def _image_bytes(size: tuple[int, int]) -> bytes:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.putpixel((size[0] // 2, size[1] // 2), (40, 90, 160, 255))
    stream = BytesIO()
    image.save(stream, format="PNG")
    image.close()
    return stream.getvalue()


def test_normalize_image_to_standard_canvas_upscales_and_centers_native_source():
    normalized = normalize_image_to_standard_canvas(_image_bytes((800, 800)))

    with Image.open(BytesIO(normalized)) as image:
        assert image.size == STANDARD_VISUAL_CANVAS_SIZE
        assert image.getchannel("A").getbbox() is not None


def test_standardize_image_file_preserves_native_receipt_and_writes_standard_copy(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(_image_bytes((800, 800)))
    destination = tmp_path / "standardized" / "source-1000x1000.png"

    receipt = standardize_image_file_to_canvas(source, destination)

    assert receipt.was_resized is True
    assert (receipt.original_width, receipt.original_height) == (800, 800)
    assert receipt.original_sha256 != receipt.standardized_sha256
    with Image.open(receipt.path) as image:
        assert image.size == STANDARD_VISUAL_CANVAS_SIZE
