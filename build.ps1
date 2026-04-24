$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.17.10-hotspot"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"

Write-Host "JAVA_HOME: $env:JAVA_HOME"
Write-Host "Java version:"
java -version

Write-Host "`nBuilding project with Gradle..."
gradle assembleDebug --stacktrace --no-daemon
