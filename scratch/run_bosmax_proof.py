import asyncio
import json
import uuid
from datetime import datetime, timezone

# We'll use the API to create the product, project, video, and scene
# Then we'll use the execute-flow-job endpoint

import aiohttp

BASE_URL = "http://127.0.0.1:8100"

async def run_proof():
    async with aiohttp.ClientSession() as session:
        # 1. Check health
        async with session.get(f"{BASE_URL}/health") as resp:
            health = await resp.json()
            if not health.get("extension_connected"):
                print("FAIL: Extension not connected")
                return

        # 2. Create product
        product_data = {
            "raw_product_title": "Bosmax image.jpg",
            "product_short_name": "Bosmax Proof",
            "source": "MANUAL"
        }
        async with session.post(f"{BASE_URL}/api/products/manual", json=product_data) as resp:
            product = await resp.json()
            product_id = product["id"]
            print(f"Created product: {product_id}")

        # 3. Patch product with local path
        patch_data = {
            "local_image_path": "C:\\Users\\USER\\Downloads\\Bosmax image.jpg",
            "image_asset_status": "READY",
            "asset_status": "DOWNLOADED"
        }
        async with session.patch(f"{BASE_URL}/api/products/{product_id}", json=patch_data) as resp:
            await resp.json()
            print("Patched product with local path")

        # 4. Create project
        project_data = {
            "name": "Bosmax F2V Verification",
            "material": "realistic"
        }
        async with session.post(f"{BASE_URL}/api/projects", json=project_data) as resp:
            project = await resp.json()
            project_id = project["id"]
            print(f"Created project: {project_id}")

        # 5. Create video
        video_data = {
            "project_id": project_id,
            "title": "Verification Video",
            "orientation": "VERTICAL"
        }
        async with session.post(f"{BASE_URL}/api/videos", json=video_data) as resp:
            video = await resp.json()
            video_id = video["id"]
            print(f"Created video: {video_id}")

        # 6. Create scene
        scene_data = {
            "video_id": video_id,
            "display_order": 0,
            "prompt": "Verification Proof: Bosmax asset integrity check."
        }
        async with session.post(f"{BASE_URL}/api/scenes", json=scene_data) as resp:
            scene = await resp.json()
            scene_id = scene["id"]
            print(f"Created scene: {scene_id}")

        # 7. Create Request (to satisfy the execute-flow-job requirement)
        request_id = f"proof_{uuid.uuid4().hex[:8]}"
        request_payload = {
            "type": "TRUE_F2V",
            "project_id": project_id,
            "video_id": video_id,
            "scene_id": scene_id,
            "orientation": "VERTICAL"
        }
        async with session.post(f"{BASE_URL}/api/requests", json=request_payload) as resp:
            request_record = await resp.json()
            # The API returns the real ID
            real_request_id = request_record["id"]
            print(f"Created request record: {real_request_id}")

        # 8. Execute Flow Job
        job_payload = {
            "request_id": real_request_id,
            "mode": "F2V",
            "aspectRatio": "9:16",
            "count": 1,
            "modelLabel": "Veo 3.1 - Lite",
            "prompt": "Verification Proof: Bosmax asset integrity check.",
            "productId": product_id,
            "stop_after_stage": "PROMPT_EDITABLE_AFTER_INSERT"
        }
        print("Submitting Flow Job...")
        async with session.post(f"{BASE_URL}/api/flow/execute-flow-job", json=job_payload) as resp:
            result = await resp.json()
            print(f"Job Submission Result: {json.dumps(result, indent=2)}")

if __name__ == "__main__":
    asyncio.run(run_proof())
