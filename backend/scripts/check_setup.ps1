param(
    [switch]$Database,
    [switch]$Tests,
    [switch]$All
)

$argsList = @("scripts/check_setup.py")
if ($Database) { $argsList += "--database" }
if ($Tests) { $argsList += "--tests" }
if ($All) { $argsList += "--all" }

python @argsList
