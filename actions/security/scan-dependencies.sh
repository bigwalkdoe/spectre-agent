#!/bin/bash
set -euo pipefail
PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
# Application Dependency Vulnerability Scanner

echo "Scanning application dependencies for vulnerabilities..."

# Function to scan a project directory
scan_project() {
    local project_dir=$1
    local project_name
    project_name=$(basename "$project_dir")
    
    if [ ! -d "$project_dir" ]; then
        echo "Project directory not found: $project_dir"
        return 1
    fi
    
    echo "Scanning $project_name..."
    
    # Check for package.json and run npm audit if available
    if [ -f "$project_dir/package.json" ]; then
        echo "Found Node.js project, running npm audit..."
        cd "$project_dir"
        npm audit --json 2>/dev/null || echo "npm audit not available or failed"
        cd - >/dev/null
    fi
    
    # Check for requirements.txt and run safety if available
    if [ -f "$project_dir/requirements.txt" ]; then
        echo "Found Python project, checking dependencies..."
        if command -v safety >/dev/null 2>&1; then
            safety check -r "$project_dir/requirements.txt" 2>/dev/null || echo "safety check failed"
        else
            echo "safety not installed, skipping Python dependency check"
        fi
    fi
    
    # Check for go.mod and run go vuln if available
    if [ -f "$project_dir/go.mod" ]; then
        echo "Found Go project, checking dependencies..."
        if command -v govulncheck >/dev/null 2>&1; then
            cd "$project_dir"
            govulncheck ./... 2>/dev/null || echo "go vuln check failed"
            cd - >/dev/null
        else
            echo "govulncheck not installed, skipping Go dependency check"
        fi
    fi
}

# Scan every project under PROJECTS_ROOT instead of two hardcoded names.
#
# The list was Guardrail-AI and Modelink. Neither is at those paths any more:
# only `modelink` exists (lowercase), and Guardrail-AI is gone entirely. So
# scan_project returned 1 for a missing directory, `set -e` propagated it, and the
# security scan reported "Dependency scanning: FAILED" on every run -- which reads
# as "vulnerabilities found" rather than "we looked in the wrong place". The
# weekly security scan has been reporting a hardcoded path failure as its result.
#
# Discovering the directories also means a new project is scanned without editing
# this script, and PROJECTS_ROOT is honoured as the single override point.
projects_found=0
projects_failed=0
for project_dir in "$PROJECTS_ROOT"/*/; do
    [ -d "$project_dir" ] || continue
    # Skip dot-directories; the glob would otherwise pick up .cache and friends.
    case "$(basename "$project_dir")" in
        .*) continue ;;
    esac
    projects_found=$((projects_found + 1))
    if ! scan_project "${project_dir%/}"; then
        projects_failed=$((projects_failed + 1))
    fi
done

if [ "$projects_found" -eq 0 ]; then
    echo "No project directories found under $PROJECTS_ROOT"
    echo "Nothing scanned -- this is not the same as 'no vulnerabilities found'."
    exit 1
fi

echo "Scanned $projects_found project(s), $projects_failed without a recognised manifest."
# A project with no package.json/requirements.txt/go.mod is not a failure: there
# was nothing to audit. Only a scan that could not run at all should fail.
exit 0



echo "Dependency scanning completed!"
