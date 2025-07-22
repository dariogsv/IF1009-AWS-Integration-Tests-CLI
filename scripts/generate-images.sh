#!/bin/bash

# Script to generate images from Mermaid diagrams
# Requires: npm install -g @mermaid-js/mermaid-cli

echo "🎨 Generating images from Mermaid diagrams..."

# Create temporary mermaid files from README
echo "Extracting Mermaid diagrams from documentation..."

# Function to extract Mermaid diagram from markdown
extract_mermaid() {
    local file=$1
    local output_dir=$2
    local diagram_name=$3
    
    # This is a simplified example - you'll need to customize based on your needs
    echo "📊 Extracting diagram: $diagram_name"
    
    # You would extract the mermaid code between ```mermaid and ``` blocks
    # and save it to a .mmd file, then convert it
    
    echo "✅ Generated: $output_dir/$diagram_name.png"
}

# Create output directories
mkdir -p docs/images/architecture
mkdir -p docs/images/diagrams
mkdir -p docs/images/workflows

echo "📁 Created image directories"

# Example: Generate high-level architecture diagram
cat > temp_architecture.mmd << 'EOF'
graph TB
    CLI[CLI Tool] --> SFN[AWS Step Functions]
    SFN --> AL[Atomic Lambda Invoker]
    AL --> HTTP[HTTP Call Lambda]
    AL --> DDB[DynamoDB Interact Lambda]
    AL --> INVOKE[Lambda Invoke Lambda]
    
    HTTP --> API[API Gateway]
    API --> LAMBDA[ProcessaPedido Function]
    LAMBDA --> TABLE[DynamoDB Table]
    
    DDB --> TABLE
    
    SFN --> CW[CloudWatch Logs]
    CLI --> CW
    
    subgraph "Test Execution Flow"
        SFN
        AL
        HTTP
        DDB
        INVOKE
    end
    
    subgraph "Application Under Test"
        API
        LAMBDA
        TABLE
    end
EOF

# Check if mermaid CLI is installed
if command -v mmdc &> /dev/null; then
    echo "🔧 Mermaid CLI found, generating PNG..."
    mmdc -i temp_architecture.mmd -o docs/images/architecture/high-level-architecture.png -t dark -b white
    rm temp_architecture.mmd
    echo "✅ Generated: docs/images/architecture/high-level-architecture.png"
else
    echo "⚠️  Mermaid CLI not found. Install with: npm install -g @mermaid-js/mermaid-cli"
    echo "📝 Temporary mermaid file saved as: temp_architecture.mmd"
    echo "🌐 You can also use https://mermaid.live/ to generate images manually"
fi

# Create a simple README for images directory
cat > docs/images/README.md << 'EOF'
# Images Directory

This directory contains visual assets for the AWS Integration Tests CLI documentation.

## Directory Structure

- `architecture/` - System architecture diagrams
- `screenshots/` - CLI and AWS Console screenshots  
- `examples/` - Configuration and code examples
- `workflows/` - Process flow diagrams

## Image Guidelines

- Use PNG for diagrams and screenshots
- Keep file sizes under 500KB
- Use descriptive filenames
- Include alt text in documentation
- Optimize for web viewing (72-96 DPI)

## Tools Used

- Mermaid (for diagrams)
- Screenshots (macOS/Windows native tools)
- Draw.io/Diagrams.net (for complex diagrams)
- AWS Architecture Icons

## Updating Images

When updating images:
1. Maintain consistent styling
2. Update related documentation
3. Optimize file sizes
4. Test image rendering in GitHub
EOF

echo "📚 Created images directory README"
echo "🎉 Image setup complete!"
echo ""
echo "Next steps:"
echo "1. Take screenshots of your CLI in action"
echo "2. Capture AWS Console screenshots"
echo "3. Create architecture diagrams using the tools mentioned"
echo "4. Replace placeholder images with real ones"
echo "5. Update documentation with proper image references"
