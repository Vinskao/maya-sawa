# One-step IBKR Client Portal Gateway login from Windows (see ibkr-gateway/README.md).
#
#   powershell -ExecutionPolicy Bypass -File ibkr-gateway\login.ps1
#
# Opens a temporary tunnel (this PC :5000 -> oke-node -> deployment/ibkr-gw :5000), opens the login page,
# waits for you to sign in (user name, password, 2FA: typed by you only, never stored), opens the
# market-data session (POST /iserver/auth/ssodh/init) and closes the tunnel. The session stays in the pod.
param(
    [string]$SshHost = "oke-node",
    [int]$Port = 5000,
    [int]$TimeoutMinutes = 10
)
$ErrorActionPreference = "Stop"
$api = "https://localhost:$Port/v1/api"

# The gateway uses a self-signed certificate; trust it for this script's own localhost calls only. Windows
# PowerShell 5.1 cannot run a script-block callback on the network thread, so the policy is a compiled class.
if (-not ("TrustGatewayCertificate" -as [type])) {
    Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class TrustGatewayCertificate : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int problem) { return true; }
}
"@
}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustGatewayCertificate
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

function Invoke-Gateway([string]$Method, [string]$Path, $Body = @{}) {
    $request = @{ Method = $Method; Uri = "$api$Path"; TimeoutSec = 15; UseBasicParsing = $true }
    # IBKR answers a POST without Content-Length with 411, so POSTs always carry a JSON body.
    if ($Method -eq "POST") { $request.Body = ($Body | ConvertTo-Json -Compress); $request.ContentType = "application/json" }
    try { return Invoke-RestMethod @request } catch { return $null }
}

if (Test-NetConnection localhost -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue) {
    throw "Port $Port is already in use (an old tunnel?). Close it or pass -Port 5001."
}
Write-Host "Opening tunnel to ibkr-gw through $SshHost ..."
# Without a terminal, ending the local ssh leaves the node's port-forward running and holding the port, so it gets a
# time limit and is also stopped explicitly below.
$forward = "kubectl port-forward deployment/ibkr-gw ${Port}:$Port"
$tunnel = Start-Process ssh -ArgumentList @("-L", "${Port}:localhost:$Port", $SshHost,
    "timeout $(($TimeoutMinutes + 2) * 60) $forward") -PassThru -WindowStyle Hidden
try {
    # The local port opens before the node's port-forward is ready; wait for the gateway itself to answer.
    # /iserver/auth/status answers 200 whether or not anyone is logged in.
    $deadline = (Get-Date).AddSeconds(45)
    while (-not ($status = Invoke-Gateway POST "/iserver/auth/status")) {
        if ($tunnel.HasExited -or (Get-Date) -gt $deadline) { throw "Gateway not reachable (is 'ssh $SshHost' working?)" }
        Start-Sleep -Seconds 2
    }

    if ($status.authenticated -and $status.connected) {
        Write-Host "Already logged in; nothing to do."
        return
    }

    Write-Host "Sign in in the browser (Chrome: type thisisunsafe on the certificate warning), then come back."
    Start-Process "https://localhost:$Port"

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $opened = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (-not $opened -and (Invoke-Gateway GET "/sso/validate")) {
            # Signed in to the portal; the market-data session still has to be opened.
            $null = Invoke-Gateway POST "/iserver/auth/ssodh/init" @{ publish = $true; compete = $true }
            $opened = $true
        }
        $status = Invoke-Gateway POST "/iserver/auth/status"
        if ($status -and $status.authenticated -and $status.connected) {
            Write-Host "Logged in. maya-sawa collects new IBKR data within about 4 minutes." -ForegroundColor Green
            return
        }
    }
    throw "Not logged in after $TimeoutMinutes minutes."
}
finally {
    if (-not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    # "[k]ubectl" keeps pkill from matching (and killing) its own shell.
    ssh $SshHost "pkill -f '[k]$($forward.Substring(1))'" | Out-Null
    Write-Host "Tunnel closed."
}
