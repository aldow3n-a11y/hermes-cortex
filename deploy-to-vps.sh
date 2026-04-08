#!/bin/bash
# CORTEX Deployment Script for aldowen.com
# Run this on your local machine

# VPS Credentials
VPS_USER="root"
VPS_HOST="43.134.227.2"
VPS_PASS="pSe-zaU-tM4-e2T"
LOCAL_FILE="/HOME/workspace/cortex/landing-page.html"

# Remote paths to try
REMOTE_PATHS=(
    "/var/www/aldowen.com/cortex/index.html"
    "/www/aldowen.com/cortex/index.html"
    "/var/www/html/cortex/index.html"
    "/srv/http/aldowen.com/cortex/index.html"
)

echo "🚀 Deploying CORTEX to aldowen.com/cortex"
echo "=========================================="

# Install sshpass if needed
if ! command -v sshpass &> /dev/null; then
    echo "📦 Installing sshpass..."
    sudo apt install -y sshpass
fi

# Create remote directory
echo ""
echo "📂 Creating remote directory..."
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "
    for path in /var/www/aldowen.com /www/aldowen.com /var/www/html /srv/http/aldowen.com; do
        if [ -d \"\$path\" ]; then
            mkdir -p \"\$path/cortex\"
            echo \"WEBROOT=\$path\"
            exit 0
        fi
    done
    echo \"NO_WEBROOT_FOUND\"
    exit 1
"

WEBROOT=$(sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "
    for path in /var/www/aldowen.com /www/aldowen.com /var/www/html /srv/http/aldowen.com; do
        if [ -d \"\$path\" ]; then
            echo \"\$path\"
            exit 0
        fi
    done
")

if [ "$WEBROOT" = "NO_WEBROOT_FOUND" ] || [ -z "$WEBROOT" ]; then
    echo "❌ Could not find web root. Manual intervention needed."
    echo "SSH to VPS and run: ls /var/www/ && ls /www/"
    exit 1
fi

echo "✅ Web root found: $WEBROOT"

# Upload file
REMOTE_FILE="$WEBROOT/cortex/index.html"
echo ""
echo "📤 Uploading landing page to $REMOTE_FILE..."

sshpass -p "$VPS_PASS" scp -o StrictHostKeyChecking=no "$LOCAL_FILE" "$VPS_USER@$VPS_HOST:$REMOTE_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Upload successful!"
    
    # Set permissions
    echo ""
    echo "🔐 Setting permissions..."
    sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "chmod 644 $REMOTE_FILE"
    
    # Verify
    echo ""
    echo "🔍 Verifying deployment..."
    sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "ls -la $WEBROOT/cortex/"
    
    echo ""
    echo "=========================================="
    echo "🎉 DEPLOYMENT COMPLETE!"
    echo "=========================================="
    echo ""
    echo "🌐 Visit: https://aldowen.com/cortex/"
    echo ""
    echo "📝 The page includes:"
    echo "   - CORTEX landing page"
    echo "   - 'Back to Main Site' link in footer"
    echo ""
else
    echo "❌ Upload failed. Check credentials and try again."
    exit 1
fi
