from typing import Set


class PolicyEngine:
    def __init__(self):
        # acciones sensibles que requieren confirmación explícita
        self.sensitive_actions: Set[str] = set(
            [
                "system.delete",
                "system.exec",
                "git.push",
                "email.send",
                "browser.fill_form",
            ]
        )

    def requires_confirmation(self, action: str) -> bool:
        return action in self.sensitive_actions
