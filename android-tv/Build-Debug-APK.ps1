# X-Stage Android TV / Tablet local debug APK builder (v1.0.77).
# Uses a checksum-pinned Gradle 8.11.1 distribution independently from Android
# Studio's Gradle 9.x installation. Public test signing only, NOT production.
param([switch]$SkipClean)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$versionFile = Join-Path (Split-Path $project -Parent) 'version.json'
$release = Get-Content $versionFile -Raw | ConvertFrom-Json
$gradleVersion = '8.11.1'
$sha256 = 'f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6'
$tools = Join-Path $env:LOCALAPPDATA 'XStageKaraoke\Gradle'
$zipPath = Join-Path $tools "gradle-$gradleVersion-bin.zip"
$gradleBat = Join-Path $tools "gradle-$gradleVersion\bin\gradle.bat"
New-Item -ItemType Directory -Path $tools -Force | Out-Null

if (-not $env:JAVA_HOME) {
    $studioJbr = 'C:\Program Files\Android\Android Studio\jbr'
    if (Test-Path (Join-Path $studioJbr 'bin\java.exe')) {
        $env:JAVA_HOME = $studioJbr
        $env:PATH = (Join-Path $studioJbr 'bin') + ';' + $env:PATH
    }
}
if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
    throw 'Java JDK 17 or newer is required. Set Gradle JDK in Android Studio first.'
}
if (-not $env:ANDROID_HOME -and -not $env:ANDROID_SDK_ROOT) {
    $sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
    if (Test-Path $sdk) {
        $env:ANDROID_HOME = $sdk
        $env:ANDROID_SDK_ROOT = $sdk
    }
}
if (-not $env:ANDROID_HOME -and -not $env:ANDROID_SDK_ROOT) {
    throw 'Android SDK not found. Install Android SDK Platform 35 from Android Studio SDK Manager.'
}

if (-not (Test-Path $gradleBat)) {
    if (-not (Test-Path $zipPath)) {
        Write-Host "Downloading official Gradle $gradleVersion (about 131 MB)..."
        Invoke-WebRequest -Uri "https://services.gradle.org/distributions/gradle-$gradleVersion-bin.zip" -OutFile $zipPath -TimeoutSec 300
    }
    $actual = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $sha256) {
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        throw 'Gradle ZIP checksum does not match the official release. Download refused.'
    }
    Write-Host 'Gradle SHA-256 verified. Extracting...'
    Expand-Archive -Path $zipPath -DestinationPath $tools -Force
}
if (-not (Test-Path $gradleBat)) { throw "Gradle executable is missing: $gradleBat" }

if (-not $env:XSTAGE_TV_OAUTH_CLIENT_ID -or -not $env:XSTAGE_TV_OAUTH_CLIENT_SECRET) {
    Write-Warning 'Google TV OAuth values are not configured; this debug APK can build but Google Drive login will not work until a correctly configured OAuth client is provided.'
}
Write-Host "Building X-Stage Android TEST APK v$($release.version) (Build $($release.build))"
$tasks = if ($SkipClean) { @('assembleDebug') } else { @('clean','assembleDebug') }
& $gradleBat -p $project --no-daemon --console=plain @tasks
if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE" }
$apk = Join-Path $project 'app\build\outputs\apk\debug\app-debug.apk'
if (-not (Test-Path $apk -PathType Leaf)) { throw 'Gradle returned success but app-debug.apk was not found.' }
$hash = (Get-FileHash $apk -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "SUCCESS: $apk"
Write-Host "SHA-256: $hash"
Write-Host 'NOTICE: This APK is signed with the public X-Stage development key and is NOT a production Google Play release.'
