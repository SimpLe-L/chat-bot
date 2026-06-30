import { ComposerPrimitive } from "@assistant-ui/react";
import { SendHorizontal } from "lucide-react";

export function Composer() {
  return (
    <ComposerPrimitive.Root className="shrink-0 border-t border-[#DDE2DA] bg-[#F9FAF7] p-4 sm:p-5">
      <div className="mx-auto flex min-h-14 max-w-4xl items-end gap-3 rounded-md border border-[#D6DDD2] bg-white p-2 shadow-soft">
        <ComposerPrimitive.Input
          className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 outline-none placeholder:text-ink/35"
          placeholder="输入你的知识库问题..."
          submitMode="enter"
        />
        <ComposerPrimitive.Send
          className="grid size-10 shrink-0 place-items-center rounded-md bg-ink text-white transition hover:bg-black disabled:cursor-not-allowed disabled:bg-ink/30"
          title="发送"
        >
          <SendHorizontal size={17} />
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
}
