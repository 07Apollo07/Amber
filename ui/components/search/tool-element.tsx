import type { ToolCallTrace } from "@/lib/types"
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool"

function parseToolArgs(args: string) {
  try {
    return JSON.parse(args)
  } catch {
    return { raw: args }
  }
}

export function ToolElement({ tool }: { tool: ToolCallTrace }) {
  const isRunning = tool.status === "running"
  const isSuccess = tool.status === "success"
  const isFailed = tool.status === "failed"
  const stateVal = isRunning ? "input-available" : isSuccess ? "output-available" : "output-error"

  return (
    <Tool>
      <ToolHeader type="dynamic-tool" state={stateVal} toolName={tool.name} title={tool.name} />
      <ToolContent>
        <ToolInput input={tool.args ? parseToolArgs(tool.args) : {}} />
        <ToolOutput
          output={isFailed ? undefined : tool.result}
          errorText={isFailed ? tool.result : undefined}
        />
      </ToolContent>
    </Tool>
  )
}
