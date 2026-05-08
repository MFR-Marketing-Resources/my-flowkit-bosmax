import type { ReactNode } from 'react'

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

export default function OperatorManual() {
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
            required="created project, target scene, uploaded image/start frame, video prompt."
            button="Submit I2V - Start Image to Video"
            warning="Not wired: explicit end frame."
          />
          <ModeCard 
            title="3. Ingredients / Refs to Video"
            status="WIRED"
            type="GENERATE_VIDEO_REFS"
            useWhen="multiple uploaded reference images guide video generation."
            required="created project, target scene, one or more uploaded refs, video prompt."
            button="Submit Ingredients / Refs to Video"
            warning="Warning: This is NOT true F2V."
          />
          <ModeCard 
            title="4. True F2V / Start + End Frames"
            status="NOT WIRED YET"
            type="GENERATE_VIDEO with end_image_media_id"
            useWhen="Expected backend path: end_image_media_id / end_scene_media_id"
            required="Missing UI: explicit start-frame selector and end-frame selector."
            button="Button not available"
            warning="Do not use GENERATE_VIDEO_REFS as F2V."
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

      <Card>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Readiness Checklist</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {[
            "Project created",
            "Target scene selected",
            "Correct lane selected",
            "Required media uploaded",
            "Prompt prepared",
            "Extension connected",
            "Queue type matches lane",
            "Not confusing F2V with Ingredients/Refs"
          ].map((item, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--text)' }}>
              <input type="checkbox" readOnly className="pointer-events-none" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
