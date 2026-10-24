"""What a kind of identity provider offers the sign-in flow."""

from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError


class ProviderError(Exception):
    """The provider could not be asked (unreachable, misconfigured): not the same as wrong credentials."""


@dataclass
class ExternalLogin:
    """A user the provider vouched for."""

    subject: str  # immutable id at the provider: the only thing an identity links on
    username: str
    email: str = ''
    first_name: str = ''
    last_name: str = ''
    groups: list[str] = field(default_factory=list)


class ProviderKind:
    """A kind of provider. ``Config`` validates a provider's settings and publishes their JSON schema."""

    key: str
    name: str
    Config: type[BaseModel]
    # Signs in with the login form's username and password (LDAP) rather than a redirect (OIDC).
    password_login = False
    case_insensitive_groups = False

    def config(self, raw: dict) -> BaseModel:
        try:
            return self.Config.model_validate(raw)
        except ValidationError as exc:
            raise ProviderError(f'invalid settings: {exc.errors()[0]["msg"]}') from exc

    def config_errors(self, raw: dict) -> list[str]:
        try:
            self.Config.model_validate(raw)
        except ValidationError as exc:
            return [f'{".".join(str(p) for p in e["loc"]) or "settings"}: {e["msg"]}' for e in exc.errors()]
        return []

    def schema(self) -> dict:
        return self.Config.model_json_schema()

    def authenticate(self, config: BaseModel, username: str, password: str) -> ExternalLogin | None:
        """The user these credentials belong to, or None if they are wrong. Raises ProviderError."""
        raise NotImplementedError

    def test(self, config: BaseModel, username: str = '') -> dict:
        """Check the settings work; with ``username``, also look that user and their groups up."""
        raise NotImplementedError
