# Synthesize per-scene narration WAVs via Windows SAPI (no downloads, fully local).
# Output: data/jobs/fixture1/segments/sceneNN.wav @ 24kHz 16-bit mono
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$root = "data/jobs/fixture1/segments"
New-Item -ItemType Directory -Force -Path $root | Out-Null

$script = Get-Content -Raw -Encoding UTF8 "tests/fixtures/fixture-script.json" | ConvertFrom-Json
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)

$i = 0
foreach ($scene in $script.scenes) {
    $i++
    $path = Join-Path $root ("scene{0:D2}.wav" -f $i)
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SetOutputToWaveFile($path, $fmt)
    $synth.Rate = 1
    $synth.Speak($scene.spoken_text)
    $synth.Dispose()
    $sec = [math]::Round((Get-Item $path).Length / 48000.0, 2)  # 24000*2 bytes/sec
    Write-Output ("scene{0:D2}.wav  {1}s" -f $i, $sec)
}
