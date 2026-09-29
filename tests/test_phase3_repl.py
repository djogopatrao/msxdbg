"""Interactive loop behavior for Phase 3 commands."""

from msxdbg.ui.repl import Repl
from test_phase3_handlers import command_context


class Reader:
    def __init__(self, events): self.events=iter(events); self.prompts=[]
    def __call__(self, prompt):
        self.prompts.append(prompt)
        event=next(self.events)
        if isinstance(event, BaseException): raise event
        return event


class Console:
    def __init__(self): self.lines=[]
    def print(self,*objects): self.lines.append(" ".join(map(str,objects)))


def test_repl_dispatches_renders_repeats_success_and_quits():
    context, _ = command_context(); reader=Reader(("print 1+2", "", "quit")); console=Console()
    assert Repl(reader=reader,console=console).run(context)==0
    assert console.lines==["3","3"]
    assert reader.prompts==["msxdbg> "]*3


def test_repl_does_not_repeat_failed_command():
    context, _ = command_context(); reader=Reader(("print 1/0", "", "exit")); console=Console()
    assert Repl(reader=reader,console=console).run(context)==0
    assert len(console.lines)==1
    assert console.lines[0].startswith("error[evaluation]")


def test_repl_handles_ctrl_c_at_prompt_and_eof():
    context, _ = command_context(); reader=Reader((KeyboardInterrupt(), "print 4", EOFError())); console=Console()
    assert Repl(reader=reader,console=console).run(context)==0
    assert console.lines==["^C","4"]


def test_repl_eof_before_any_command_is_clean():
    context, _ = command_context(); console=Console()
    assert Repl(reader=Reader((EOFError(),)),console=console).run(context)==0
    assert console.lines==[]


def test_repl_processes_actions_and_never_repeats_confirmation_commands():
    context, _ = command_context(); console=Console()
    reader=Reader(("clear", "", "reset", "", "q"))
    assert Repl(reader=reader,console=console).run(context)==0
    assert console.lines[:2] == ["\x1b[H\x1b[2J\x1b[3J"] * 2
    explanations = [line for line in console.lines if "reset yes" in line]
    assert len(explanations) == 1
