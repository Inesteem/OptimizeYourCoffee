import subprocess
import json
import re
import sys
from pathlib import Path

def get_variety_value(lines, header, variety_index):
    """
    Finds a header in the lines and returns the value on the line below it,
    trying to account for column positions.
    """
    for i, line in enumerate(lines):
        if header in line:
            pos = line.find(header)
            # Look at the next line and try to grab text at the same position
            if i + 2 < len(lines):
                val_line = lines[i + 2]
                # Extract chunk around the header position
                chunk = val_line[pos:pos+30].strip()
                # Some headers are very close, so we might need to be careful
                # but for this PDF, 30 chars usually covers one column.
                return chunk
    return ""

def extract_coffee_data(pdf_path):
    print(f"Reading {pdf_path} with -layout...")
    
    try:
        result = subprocess.run(['pdftotext', '-layout', str(pdf_path), '-'], 
                               capture_output=True, text=True, check=True)
        text = result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return None

    # Split into sections by "ARABICA" or "ROBUSTA" markers
    # Using a look-ahead to keep the marker at the start of each split
    sections = re.split(r'\n\s*(ARABICA|ROBUSTA)\n', text)
    
    varieties = {}
    
    # re.split with groups returns [prefix, marker1, content1, marker2, content2...]
    for i in range(1, len(sections), 2):
        species = sections[i].capitalize()
        content = sections[i+1]
        
        lines = content.split('\n')
        # First non-empty line after ARABICA/ROBUSTA is the name
        name = ""
        desc_lines = []
        found_name = False
        
        for j, line in enumerate(lines):
            stripped = line.strip()
            if not stripped: continue
            if not found_name:
                # Filter out some noise
                if any(x in stripped for x in ["Varieties", "YIELD POTENTIAL", "OPTIMAL"]):
                    continue
                name = stripped
                found_name = True
            elif "STATURE" in line or "YIELD POTENTIAL" in line or "Background" in line or "Agronomics" in line:
                break
            else:
                desc_lines.append(stripped)
        
        if not name: continue
        
        # Extract variety-specific metadata
        variety_entry = {
            "species": species,
            "desc": " ".join(desc_lines).split("STATURE")[0].strip(),
            "stature": get_variety_value(lines, "STATURE", 0),
            "leaf_tip": get_variety_value(lines, "LEAF TIP COLOR", 0),
            "bean_size": get_variety_value(lines, "BEAN SIZE", 0),
            "yield_potential": get_variety_value(lines, "YIELD POTENTIAL", 0),
            "optimal_altitude": get_variety_value(lines, "OPTIMAL ALTITUDE", 0)
        }
        
        varieties[name] = variety_entry
        
    return varieties

if __name__ == "__main__":
    pdf = Path("reference/full_coffee_catalog.pdf")
    if not pdf.exists():
        print("PDF not found.")
        sys.exit(1)
        
    data = extract_coffee_data(pdf)
    if data:
        output_file = Path("notes/extracted_varieties.json")
        # Ensure directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(data, f, indent=4)
        print(f"Successfully extracted {len(data)} varieties to {output_file}")
