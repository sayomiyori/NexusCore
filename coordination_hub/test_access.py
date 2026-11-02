"""Isolated Windows ACL experiment. This is not a production provisioner."""
import os
import stat
import subprocess
import tempfile
from pathlib import Path

SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = $env:NEXUS_HUB_ACL_TEST_DIR
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$system = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$admins = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$acl = [System.Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($user)
$acl.SetAccessRuleProtection($true, $false)
$inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
foreach ($sid in @($user, $system, $admins)) {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inherit, [System.Security.AccessControl.PropagationFlags]::None, [System.Security.AccessControl.AccessControlType]::Allow)
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $path -AclObject $acl
$actual = Get-Acl -LiteralPath $path
if (-not $actual.AreAccessRulesProtected) { throw 'ACL inheritance remains enabled' }
if ($actual.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $user.Value) { throw 'Unexpected owner' }
$expected = @($user.Value, $system.Value, $admins.Value) | Sort-Object -Unique
$rules = @($actual.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$found = @($rules | ForEach-Object { $_.IdentityReference.Value }) | Sort-Object -Unique
if (Compare-Object $expected $found) { throw 'Unexpected ACL principals' }
foreach ($rule in $rules) {
    if ($rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl' -or $rule.InheritanceFlags -ne $inherit -or $rule.PropagationFlags -ne 'None') {
        throw 'Unexpected access rule'
    }
}
"""

def restrict_test_directory(directory):
    """Configure and verify only an empty directory inside the temporary root."""
    if os.name != 'nt':
        raise OSError('Windows only')
    original = Path(directory)
    info = original.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Invalid test directory')
    path = original.resolve(strict=True)
    root = Path(tempfile.gettempdir()).resolve(strict=True)
    if path == root or not path.is_relative_to(root) or any(path.iterdir()):
        raise ValueError('Only empty temporary directories are supported')
    env = dict(os.environ)
    env['NEXUS_HUB_ACL_TEST_DIR'] = str(path)
    completed = subprocess.run(['pwsh.exe', '-NoProfile', '-NonInteractive', '-Command', SCRIPT],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=15, env=env, check=False)
    if completed.returncode != 0:
        raise OSError('Test ACL configuration or verification failed')
