import sys
import os

filepath = 'agent/services/flow_client.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = [
    '    async def execute_flow_job(self, job_data: dict) -> dict:\n',
    '        """Trigger DOM automation in the extension for a generation job."""\n',
    '        return await self._send("EXECUTE_FLOW_JOB", {"job": job_data}, timeout=120)\n',
    '\n'
]

found = False
for i, line in enumerate(lines):
    if 'def _client_context' in line:
        lines.insert(i, ''.join(new_lines))
        found = True
        break

if found:
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print('SUCCESS')
else:
    print('NOT FOUND')
