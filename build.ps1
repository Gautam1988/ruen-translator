# Build RuEn Translator into dist\RuEnTranslator (folder app) and a portable zip.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
$version = (& $py -c "import rutrans; print(rutrans.__version__)").Trim()

if (-not (Test-Path "models\opus-mt-ru-en\model.bin")) {
    throw "Model missing. Run: $py tools\convert_model.py build_src\opus_ru_en models\opus-mt-ru-en"
}
if (-not (Test-Path "models\ocr\eslav_PP-OCRv5_rec_mobile.onnx")) {
    throw "OCR models missing. Run: $py tools\get_ocr_models.py"
}

# PyInstaller wipes dist\RuEnTranslator. Set aside anything a user put there (e.g. test
# documents) and put it back after the build; it is not included in the portable zip.
$app = "dist\RuEnTranslator"
$keep = "dist\_kept_during_build"
if (Test-Path $app) {
    $extra = Get-ChildItem $app | Where-Object { $_.Name -notin @("RuEnTranslator.exe", "_internal") }
    if ($extra) {
        New-Item -ItemType Directory -Force $keep | Out-Null
        $extra | Move-Item -Destination $keep -Force
        "Set aside during build: " + (($extra | ForEach-Object Name) -join ", ")
    }
}

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name RuEnTranslator `
    --icon rutrans\icon.ico `
    --add-data "rutrans\icon.ico;rutrans" `
    --add-data "LICENSE;rutrans\docs" --add-data "THIRD_PARTY_NOTICES.md;rutrans\docs" `
    --add-data "PRIVACY.md;rutrans\docs" `
    --add-data "models\opus-mt-ru-en;models\opus-mt-ru-en" `
    --add-data "models\ocr;models\ocr" `
    --collect-binaries ctranslate2 `
    --collect-data rapidocr --collect-binaries onnxruntime `
    --exclude-module pymupdf4llm --exclude-module pymupdf.layout `
    --exclude-module rapidocr.inference_engine.pytorch --exclude-module rapidocr.inference_engine.paddle `
    --exclude-module rapidocr.inference_engine.openvino --exclude-module rapidocr.inference_engine.mnn `
    --exclude-module rapidocr.inference_engine.tensorrt `
    --exclude-module tkinter --exclude-module matplotlib --exclude-module torch `
    --exclude-module transformers --exclude-module huggingface_hub --exclude-module sacrebleu `
    --exclude-module onnx `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtMultimedia --exclude-module PySide6.Qt3DCore `
    run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Drop Qt pieces a plain widgets app never loads (~50 MB).
$qt = "dist\RuEnTranslator\_internal\PySide6"
$prune = @("opengl32sw.dll", "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll",
           "Qt6QmlWorkerScript.dll", "Qt6Pdf.dll", "Qt6VirtualKeyboard.dll", "Qt6OpenGL.dll",
           "plugins\imageformats\qpdf.dll", "plugins\platforminputcontexts", "translations")
foreach ($p in $prune) {
    if (Test-Path "$qt\$p") { Remove-Item -Recurse -Force "$qt\$p" }
}
# RapidOCR's default (Chinese/Latin) models are not used; ours are in models\ocr.
Get-ChildItem "dist\RuEnTranslator\_internal\rapidocr\models" -Filter "PP-OCRv6*" -ErrorAction SilentlyContinue |
    Remove-Item -Force
# python-docx's unpacked template sources are unused (it reads templates\default.docx), and the
# file name "[Content_Types].xml" is reserved in MSIX packages, so makeappx refuses it.
$tpl = "dist\RuEnTranslator\_internal\docx\templates\default-docx-template"
if (Test-Path $tpl) { Remove-Item -Recurse -Force $tpl }
# OpenCV's video decoder is not needed for still images (~30 MB).
Get-ChildItem "dist\RuEnTranslator\_internal\cv2" -Filter "opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue |
    Remove-Item -Force

$zip = "dist\RuEnTranslator-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\RuEnTranslator" -DestinationPath $zip
$size = (Get-ChildItem dist\RuEnTranslator -Recurse | Measure-Object Length -Sum).Sum / 1MB
if (Test-Path $keep) {
    Get-ChildItem $keep | Move-Item -Destination $app -Force
    Remove-Item $keep -Force
    "Put back: user files in $app"
}
"Built dist\RuEnTranslator\RuEnTranslator.exe ({0:N0} MB) and $zip ({1:N0} MB)" -f $size, ((Get-Item $zip).Length / 1MB)
