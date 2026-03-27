# maascli Subsystem

## Purpose

Command-line interface for MAAS that provides comprehensive CLI operations for managing deployments. Enables users and scripts to perform all MAAS operations from the command line, serving as an alternative to the web UI and foundation for automation.

**Status**: Active - primary CLI tool for MAAS.

## Location

`src/maascli`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **argparse**: Command-line argument parsing
- **MAAS API Client**: Communication with MAAS API

### Key Libraries
- **argparse**: CLI argument parsing
- **colorama**: Terminal color output
- **requests**: HTTP client for API
- **pyyaml**: Configuration file handling

## Architectural Constraints

### API-Driven Design

CLI is a thin client communicating exclusively via MAAS API:
- No direct database access
- All operations via REST API
- OAuth authentication
- Stateless operation
- No business logic in CLI

### User Experience Focus

Designed for both interactive and scripted use:
- Clear, actionable error messages
- Human-readable output by default
- Machine-readable formats available (JSON, YAML)
- Progress indicators for long operations
- Comprehensive help documentation

### Profile-Based Configuration

Support multiple MAAS profiles for different environments:
- Store multiple server configurations
- Switch between environments easily
- Secure credential storage
- Per-profile settings

## Key Patterns

> **See**: [python-patterns.md](../../skills/languages/python-patterns.md) for common Python patterns.

### Command Structure

Hierarchical command organization with subcommands:

```python
from maascli.command import Command

class MachinesCommand(Command):
    """Manage machines in MAAS."""
    
    subcommands = {
        'list': ListMachinesCommand,
        'read': ReadMachineCommand,
        'create': CreateMachineCommand,
        'deploy': DeployMachineCommand,
        'release': ReleaseMachineCommand,
    }

class DeployMachineCommand(Command):
    """Deploy a machine."""
    
    def add_arguments(self, parser):
        parser.add_argument('system_id', help='System ID of machine')
        parser.add_argument('--os', required=True, help='OS to deploy')
        parser.add_argument('--wait', action='store_true', help='Wait for completion')
    
    def execute(self, args):
        client = self.get_client()
        machine = client.machines.deploy(
            system_id=args.system_id,
            os=args.os
        )
        self.print_result(machine)
        
        if args.wait:
            self.wait_for_deployment(machine)
```

### Error Handling Pattern

User-friendly error messages for all failure scenarios:

```python
class CommandError(Exception):
    """User-facing command error."""
    pass

def execute_command(command, args):
    try:
        return command.execute(args)
    except APIError as e:
        if e.status_code == 404:
            raise CommandError(f"Resource not found: {e.detail}")
        elif e.status_code == 401:
            raise CommandError("Authentication failed. Run 'maas login' first.")
        elif e.status_code == 403:
            raise CommandError("Permission denied.")
        else:
            raise CommandError(f"API error: {e.detail}")
    except ConnectionError:
        raise CommandError("Cannot connect to MAAS server. Check URL and network.")
    except ValueError as e:
        raise CommandError(f"Invalid input: {e}")
```

### Output Formatting

Multiple output formats for different use cases:

```python
from enum import Enum
import json
import yaml

class OutputFormat(Enum):
    HUMAN = "human"
    JSON = "json"
    YAML = "yaml"

class OutputFormatter:
    def format(self, data, format: OutputFormat):
        if format == OutputFormat.JSON:
            return json.dumps(data, indent=2)
        elif format == OutputFormat.YAML:
            return yaml.dump(data, default_flow_style=False)
        else:
            return self._format_human(data)
    
    def _format_human(self, data):
        """Human-readable format with color."""
        if isinstance(data, dict):
            return '\n'.join(f"{k}: {v}" for k, v in data.items())
        elif isinstance(data, list):
            return '\n'.join(str(item) for item in data)
        return str(data)
```

### Profile Management

Manage multiple MAAS server profiles:

```python
class ProfileManager:
    """Manage MAAS CLI profiles."""
    
    def __init__(self, config_dir="~/.maas-cli"):
        self.config_dir = Path(config_dir).expanduser()
        self.config_file = self.config_dir / "profiles.yaml"
    
    def add_profile(self, name: str, url: str, apikey: str):
        """Add a new profile."""
        profiles = self.load_profiles()
        profiles[name] = {
            'url': url,
            'apikey': apikey
        }
        self.save_profiles(profiles)
    
    def get_profile(self, name: str) -> dict:
        """Get profile by name."""
        profiles = self.load_profiles()
        if name not in profiles:
            raise CommandError(f"Profile '{name}' not found")
        return profiles[name]
    
    def list_profiles(self) -> list[str]:
        """List all profile names."""
        return list(self.load_profiles().keys())
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Mock API Client

Always mock the API client in CLI tests:

```python
import pytest
from unittest.mock import Mock, MagicMock

@pytest.fixture
def mock_api_client():
    """Mock MAAS API client."""
    client = MagicMock()
    client.machines.list.return_value = [
        {'system_id': 'abc123', 'hostname': 'machine1', 'status': 'Ready'}
    ]
    return client

def test_list_machines(mock_api_client, capsys):
    """Test listing machines."""
    cmd = ListMachinesCommand(client=mock_api_client)
    cmd.execute(Mock(format='json'))
    
    captured = capsys.readouterr()
    assert 'machine1' in captured.out
    mock_api_client.machines.list.assert_called_once()
```

### Test Output Formats

Verify all output formats work correctly:

```python
def test_output_formats():
    """Test different output formats."""
    data = {'hostname': 'test', 'status': 'ready'}
    formatter = OutputFormatter()
    
    # JSON output
    json_output = formatter.format(data, OutputFormat.JSON)
    assert json.loads(json_output) == data
    
    # YAML output
    yaml_output = formatter.format(data, OutputFormat.YAML)
    assert yaml.safe_load(yaml_output) == data
    
    # Human output
    human_output = formatter.format(data, OutputFormat.HUMAN)
    assert 'hostname' in human_output
    assert 'test' in human_output
```

### Test Error Handling

Test error messages are user-friendly:

```python
def test_connection_error_handling(mock_api_client):
    """Test connection error handling."""
    mock_api_client.machines.list.side_effect = ConnectionError()
    
    cmd = ListMachinesCommand(client=mock_api_client)
    
    with pytest.raises(CommandError, match="Cannot connect"):
        cmd.execute(Mock())
```

### Running Tests

```bash
# All CLI tests
pytest src/maascli/tests/

# Specific command tests
pytest src/maascli/tests/test_machines.py

# With coverage
pytest --cov=maascli src/maascli/tests/
```

## Development Guidelines

### Adding New Commands

1. Create command class extending `Command`
2. Implement `add_arguments()` for CLI arguments
3. Implement `execute()` for command logic
4. Add to parent command's `subcommands` dict
5. Write tests with mocked API client

### Command Design Principles

- **Single Responsibility**: Each command does one thing
- **Consistent Interface**: Follow established patterns
- **Clear Help Text**: Comprehensive help for all arguments
- **Validation**: Validate inputs before API calls
- **Error Messages**: User-friendly, actionable errors

### API Client Usage

Always use the API client abstraction:

```python
class Command:
    def get_client(self):
        """Get authenticated API client."""
        profile = self.profile_manager.get_active_profile()
        return MAASClient(
            url=profile['url'],
            apikey=profile['apikey']
        )
    
    def execute(self, args):
        client = self.get_client()
        # Use client methods
        result = client.machines.list()
        return result
```

## Integration Points

### MAAS API Server
- All operations via REST API
- OAuth 1.0 authentication
- JSON request/response format
- See [maasapiserver.md](./maasapiserver.md)

### Profile Configuration
- Stored in `~/.maas-cli/profiles.yaml`
- Contains server URLs and credentials
- Active profile tracked in config

### Exit Codes
- `0`: Success
- `1`: General error
- `2`: Command-line usage error
- `3`: Authentication error
- `4`: Permission denied

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Exposing Credentials

❌ **Don't** log or display credentials:
```python
# WRONG!
print(f"Using API key: {apikey}")
logger.debug(f"Auth: {profile['apikey']}")
```

✅ **Do** protect credentials:
```python
# Correct
logger.debug(f"Using profile: {profile['name']}")
print("Authentication successful")
```

### Poor Error Messages

❌ **Don't** expose technical details to users:
```python
# WRONG!
raise CommandError(f"HTTP 500: {traceback.format_exc()}")
```

✅ **Do** provide actionable messages:
```python
# Correct
raise CommandError("Server error. Please try again or contact support.")
```

### Blocking Operations

❌ **Don't** block without feedback:
```python
# WRONG!
while not deployment_complete():
    time.sleep(5)  # Silent waiting
```

✅ **Do** provide progress feedback:
```python
# Correct
with ProgressBar("Deploying...") as progress:
    while not deployment_complete():
        progress.update()
        time.sleep(5)
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### Credential Storage
- Store credentials in user-only readable files (600 permissions)
- Never log or display API keys
- Support credential rotation

### Input Validation
- Validate all user inputs before API calls
- Sanitize file paths
- Prevent command injection in shell operations
- See [input-validation.md](../../skills/techniques/input-validation.md)

### Secure Communication
- Use HTTPS for API communication
- Verify SSL certificates by default
- Allow certificate verification override only with explicit flag

## Performance Considerations

### API Call Optimization
- Batch operations where possible
- Use pagination for large result sets
- Cache profile data locally
- Minimize redundant API calls

### Large Output Handling
- Stream large responses instead of loading entirely
- Use pagination for list commands
- Support filtering server-side when available

### Startup Time
- Lazy load dependencies
- Defer expensive operations
- Quick response for help/version commands

## Additional Resources

- **argparse**: https://docs.python.org/3/library/argparse.html
- **MAAS API**: See API documentation
- **Related**: [python-patterns.md](../../skills/languages/python-patterns.md), [maasapiserver.md](./maasapiserver.md)