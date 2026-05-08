import type { ReactNode } from 'react'
import type { CreatedState, UploadedAsset } from '../../types'

function Card({ children }: { children: ReactNode }) {
  return (
    <section
      className="rounded-lg p-4 flex flex-col gap-3"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      {children}
    </section>
  )
}

function ModeCard({ title, status, type, useWhen, required, button, warning }: {
  title: string
  status: string
  type: string
  useWhen: string
  required: string
  button: string
  warning?: string
}) {
  const isWired = status === 'WIRED'
  return (
    <div className="rounded p-3 flex flex-col gap-2" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold" style={{ color: 'var(--text)' }}>{title}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{
          background: isWired ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
          color: isWired ? 'var(--green)' : 'var(--red)',
          border: `1px solid ${isWired ? 'var(--green)' : 'var(--red)'}`
        }}>
          {status}
        </span>
      </div>
      <div className="text-[10px] flex flex-col gap-1" style={{ color: 'var(--muted)' }}>
        <div><strong style={{ color: 'var(--text)' }}>Request type:</strong> {type}</div>
        <div><strong style={{ color: 'var(--text)' }}>Use when:</strong> {useWhen}</div>
        <div><strong style={{ color: 'var(--text)' }}>Required:</strong> {required}</div>
      </div>
      {warning && (
        <div className="text-[10px] p-1.5 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: 'var(--yellow)', border: '1px solid var(--yellow)' }}>
          {warning}
        </div>
      )}
      <div className="mt-auto pt-2">
        <div className="text-[10px] font-bold text-center p-1.5 rounded" style={{ background: 'var(--border)', color: 'var(--muted)', border: '1px solid var(--border)' }}>
          {button}
        </div>
      </div>
    </div>
  )
}

function EvidenceSubsection({ title, children }: { title: string, children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--accent)' }}>{title}</div>
      <div className="text-[10px]" style={{ color: 'var(--text)' }}>{children}</div>
    </div>
  )
}

function Badge({ children, type = 'info' }: { children: ReactNode, type?: 'info' | 'warn' | 'success' | 'danger' }) {
  const colors = {
    info: { bg: 'rgba(59,130,246,0.1)', text: 'var(--blue)', border: 'var(--blue)' },
    warn: { bg: 'rgba(234,179,8,0.1)', text: 'var(--yellow)', border: 'var(--yellow)' },
    success: { bg: 'rgba(34,197,94,0.1)', text: 'var(--green)', border: 'var(--green)' },
    danger: { bg: 'rgba(239,68,68,0.1)', text: 'var(--red)', border: 'var(--red)' }
  }
  const c = colors[type]
  return (
    <span className="text-[9px] px-1 py-0.5 rounded font-bold mr-1 inline-block mb-1" style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}` }}>
      {children}
    </span>
  )
}

interface OperatorManualProps {
  created: CreatedState | null
  selectedSceneId: string
  uploadedAssets: UploadedAsset[]
  manualPrompt: string
  resolvedVideoPromptReady: boolean
  submittingManual: boolean
  uploadingAssets: boolean
  backendConnected: boolean
  extensionConnected: boolean
}

export default function OperatorManual({
  created,
  selectedSceneId,
  uploadedAssets,
  manualPrompt,
  resolvedVideoPromptReady,
  submittingManual,
  uploadingAssets,
  backendConnected,
  extensionConnected
}: OperatorManualProps) {
  const checklist = [
    { label: "Backend connected", pass: backendConnected },
    { label: "Extension connected", pass: extensionConnected },
    { label: "Project created", pass: !!created },
    { label: "Target scene selected", pass: !!selectedSceneId },
    { label: "Uploaded assets ready", pass: uploadedAssets.length > 0 },
    { label: "Resolved video prompt ready", pass: resolvedVideoPromptReady || manualPrompt.trim().length > 0 },
    { label: "Upload not running", pass: !uploadingAssets },
    { label: "Submit not running", pass: !submittingManual },
    { label: "F2V not confused with Ingredients/Refs", pass: true }
  ]

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Operator Manual / SOP</h3>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          <ModeCard
            title="1. IMG / Edit Image"
            status="WIRED"
            type="EDIT_IMAGE"
            useWhen="user uploads a base product/photo and wants an edited/generated image."
            required="created project, target scene, uploaded image, prompt if user wants override."
            button="Submit IMG / Edit Image"
            warning="Not verified: Google Flow DOM selector automation."
          />
          <ModeCard
            title="2. I2V / Start Image to Video"
            status="WIRED"
            type="GENERATE_VIDEO"
            useWhen="first uploaded image becomes the start frame for video."
            required="created project, target scene, uploaded image/start frame, resolved video prompt."
            button="Submit I2V - Start Image to Video"
            warning="Not wired: explicit end frame."
          />
          <ModeCard
            title="3. Ingredients / Refs to Video"
            status="WIRED"
            type="GENERATE_VIDEO_REFS"
            useWhen="multiple uploaded reference images guide video generation."
            required="created project, target scene, one or more uploaded refs, resolved video prompt."
            button="Submit Ingredients / Refs to Video"
            warning="Warning: This is NOT true F2V."
          />
          <ModeCard
            title="4. True F2V / Start + Optional End Frame"
            status="WIRED IN OPERATOR"
            type="GENERATE_VIDEO + end_scene_media_id"
            useWhen="transitioning between a specific start frame and end frame."
            required="created project, target scene, uploaded start asset, optional end asset, resolved video prompt."
            button="Submit True F2V / Start Frame + Optional End"
            warning="Chrome DOM automation: still LIVE TEST REQUIRED."
          />
          <ModeCard
            title="5. Direct T2V"
            status="NOT NATIVE / NOT VERIFIED"
            type="N/A"
            useWhen="Current supported path: prompt -> image -> video"
            required="Do not expose direct submit until native queue path is verified."
            button="Button not available"
          />
        </div>
      </Card>

      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
        <Card>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Google Flow Evidence Notes</h3>
          <div className="flex flex-col gap-3">
            <EvidenceSubsection title="IMAGE / IMG Evidence">
              <div><Badge type="info">SOURCE EVIDENCE</Badge> Workspace uses Nano Banana 2 / Pro.</div>
              <div>Ratios: 16:9, 9:16, 1:1, 3:4, 4:3. Tools: Doodle, Box, Lasso, Annotation, Crop.</div>
              <div style={{ color: 'var(--muted)' }}><Badge type="warn">LIVE TEST REQUIRED</Badge> Exact DOM selectors for toggle, prompt, and generate buttons.</div>
            </EvidenceSubsection>

            <EvidenceSubsection title="T2V Evidence">
              <div><Badge type="info">SOURCE EVIDENCE</Badge> External API evidence exists for direct T2V: <code>/v1/video:batchAsyncGenerateVideoText</code>.</div>
              <div style={{ color: 'var(--muted)' }}><Badge type="danger">REPO NOT WIRED</Badge> This repo does not expose a native T2V queue yet. Path is prompt -&gt; image -&gt; video.</div>
            </EvidenceSubsection>

            <EvidenceSubsection title="I2V Evidence">
              <div><Badge type="info">SOURCE EVIDENCE</Badge> Uses attached image asset plus video prompt.</div>
              <div><Badge type="success">REPO WIRED</Badge> Maps to <code>GENERATE_VIDEO</code> lane.</div>
              <div style={{ color: 'var(--muted)' }}><Badge type="warn">LIVE TEST REQUIRED</Badge> Exact native file input selector.</div>
            </EvidenceSubsection>

            <EvidenceSubsection title="F2V / Frames Evidence">
              <div><Badge type="info">SOURCE EVIDENCE</Badge> Labels: "Select start", "Select end". End frame is optional.</div>
              <div><Badge type="success">QUEUE WIRED</Badge> True F2V maps to <code>GENERATE_VIDEO</code> with optional <code>end_scene_media_id</code>.</div>
              <div style={{ color: 'var(--muted)' }}><Badge type="warn">LIVE TEST REQUIRED</Badge> Live Flow execution still depends on worker + extension connected path.</div>
            </EvidenceSubsection>

            <EvidenceSubsection title="Ingredients / Refs Evidence">
              <div><Badge type="info">SOURCE EVIDENCE</Badge> Labels: "Ingredient 1", "Ingredient 2". Claimed max 14 references (4 char / 10 object).</div>
              <div style={{ color: 'var(--yellow)' }}><Badge type="warn">DO NOT HARDCODE</Badge> Source evidence claims max 14 references. Runtime-detect actual capacity before automation.</div>
              <div style={{ color: 'var(--red)' }}><Badge type="danger">Veo 3.1 Lite Limitation</Badge> Cannot process Ingredients/Refs or 4K.</div>
            </EvidenceSubsection>
          </div>
        </Card>

        <Card>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Live Test Required</h3>
          <div className="text-[10px] p-2 rounded" style={{ background: 'rgba(239,68,68,0.05)', border: '1px solid var(--red)', color: 'var(--text)' }}>
            <div className="font-bold mb-1 uppercase tracking-tight" style={{ color: 'var(--red)' }}>Before Chrome Extension DOM Automation</div>
            <ul className="list-disc pl-3 flex flex-col gap-1" style={{ color: 'var(--muted)' }}>
              <li>Exact CSS/XPath/ARIA selectors for all inputs/buttons</li>
              <li>Native upload input structure and event triggers</li>
              <li>Submit button enabled/disabled state rules</li>
              <li>Polling response JSON shape and status keys</li>
              <li>Output media URL extraction path</li>
              <li>CAPTCHA / Auth challenge detection patterns</li>
              <li>Current model dropdown values vs backend IDs</li>
              <li>Current upload capacity for active account (Ingredients)</li>
            </ul>
          </div>

          <h3 className="text-sm font-bold mt-2" style={{ color: 'var(--text)' }}>Readiness Checklist</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {checklist.map((item, i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                <span className="text-[10px]" style={{ color: 'var(--text)' }}>{item.label}</span>
                <span className="text-[10px] font-bold" style={{ color: item.pass ? 'var(--green)' : 'var(--red)' }}>
                  {item.pass ? 'PASS' : 'BLOCKED'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
