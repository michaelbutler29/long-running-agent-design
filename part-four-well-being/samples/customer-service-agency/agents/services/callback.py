"""Shared callback handler for streaming agent output with role labels."""


class AgentCallbackHandler:
    def __init__(self, label: str):
        self._label = label
        self._at_line_start = True
        self._last_tool = None

    def __call__(self, **kwargs):
        if "data" in kwargs:
            text = kwargs["data"]
            out = ""
            for ch in text:
                if self._at_line_start:
                    out += f"[{self._label}] "
                    self._at_line_start = False
                out += ch
                if ch == "\n":
                    self._at_line_start = True
            if out:
                print(out, end="", flush=True)
            self._last_tool = None
        elif "current_tool_use" in kwargs and kwargs["current_tool_use"].get("name"):
            current_tool_use = kwargs["current_tool_use"]
            name = current_tool_use["name"]
            if current_tool_use != self._last_tool:
                self._last_tool = current_tool_use
                tool_input = current_tool_use.get("input", {})
                if tool_input:
                    args_str = ", ".join(f"{k}={repr(v)[:80]}" for k, v in tool_input.items())
                    print(f"\n[{self._label}] Using tool: {name}({args_str})")
                else:
                    print(f"\n[{self._label}] Using tool: {name}")
                self._at_line_start = True


class QuietCallbackHandler:
    """No streaming output — for concurrent sessions where interleaving is noise."""

    def __init__(self, label: str):
        self._label = label

    def __call__(self, **kwargs):
        pass
