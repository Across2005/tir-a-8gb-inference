param(
    [Parameter(Mandatory = $true)][string]$Docx
)
$ErrorActionPreference = "Stop"
$path = (Resolve-Path $Docx).Path
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($path)
    $doc.Fields.Update() | Out-Null
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Repaginate()
    $doc.Save()
    $pdf = [System.IO.Path]::ChangeExtension($path, ".pdf")
    $doc.ExportAsFixedFormat($pdf, 17)
    $pages = $doc.ComputeStatistics(2)
    Write-Output "WORD_OK pages=$pages pdf=$pdf"
    $doc.Close($false)
} finally {
    $word.Quit()
}
