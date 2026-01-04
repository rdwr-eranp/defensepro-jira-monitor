"""
Quick runner for gate analysis with preset values
"""
import subprocess
import sys

# Preset values
version = "10.12.0.0"
builds = "83-106"

print(f"Running gate analysis for version {version}, builds {builds}")
print()

# Create input string
input_data = f"{version}\n{builds}\n"

# Run the script with input
process = subprocess.Popen(
    [sys.executable, "generate_gate_analysis.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

output, _ = process.communicate(input=input_data)
print(output)
