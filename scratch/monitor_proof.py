import sqlite3
import time
import json

DB_PATH = 'flow_agent.db'
REQUEST_ID = 'bosmax_live_proof_final_v7'

REQUIRED_PASS = [
    'FLOW_ROOT_OPENED',
    'NEW_PROJECT_CLICKED',
    'FLOW_TYPE_VIDEO_SELECTED',
    'FLOW_SUBMODE_FRAMES_SELECTED',
    'F2V_COMPOSER_READY',
    'FLOW_ASPECT_9_16_SELECTED',
    'FLOW_COUNT_1X_SELECTED',
    'FLOW_MODEL_VEO_3_1_LITE_SELECTED',
    'START_SLOT_VISIBLE',
    'PROMPT_FIELD_VISIBLE',
    'F2V_WORKSPACE_READY',
    'FLOW_MODE_VERIFIED',
    'START_FRAME_UPLOAD_ATTEMPTED',
    'START_FRAME_ATTACHED',
    'START_FRAME_VERIFIED',
    'PROMPT_FIELD_FOUND',
    'PROMPT_VISIBLE',
    'PROMPT_EDITABLE_AFTER_INSERT',
    'STOP_AFTER_STAGE_REACHED'
]

REQUIRED_ABSENT = [
    'GENERATE_CLICKED',
    'GENERATION_STARTED',
    'VIDEO_JOB_RUNNING_OR_GENERATED'
]

def poll():
    print(f"Monitoring telemetry for {REQUEST_ID}...")
    seen_stages = set()
    failed_stage = None
    fail_message = None
    
    start_time = time.time()
    timeout = 180 # 3 minutes
    
    while time.time() - start_time < timeout:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT stage, status, message FROM request_stage_event WHERE request_id = ? ORDER BY timestamp ASC", (REQUEST_ID,))
        rows = cursor.fetchall()
        conn.close()
        
        for stage, status, message in rows:
            if stage not in seen_stages:
                print(f"[{stage}] {status} {message or ''}")
                seen_stages.add(stage)
                if status == 'FAIL':
                    failed_stage = stage
                    fail_message = message
                    break
        
        if failed_stage or 'STOP_AFTER_STAGE_REACHED' in seen_stages:
            break
            
        time.sleep(2)
        
    # Final check
    pass_stages = [s for s in REQUIRED_PASS if s in seen_stages]
    absent_stages = [s for s in REQUIRED_ABSENT if s in seen_stages]
    
    report = {
        "STATUS": "PASS" if not failed_stage and 'STOP_AFTER_STAGE_REACHED' in seen_stages else "FAIL",
        "REQUEST_ID": REQUEST_ID,
        "FIRST_FAIL_STAGE": failed_stage,
        "FULL_FAIL_MESSAGE": fail_message,
        "PASS_STAGES": pass_stages,
        "ABSENT_STAGES": absent_stages,
    }
    
    print("\nFINAL REPORT:")
    print(json.dumps(report, indent=2))
    
    with open('scratch/proof_report.json', 'w') as f:
        json.dump(report, f)

if __name__ == "__main__":
    poll()
