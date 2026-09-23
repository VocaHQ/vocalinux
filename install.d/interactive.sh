#!/bin/bash
# Sourced by install.sh after it has resolved the local or tagged repository.
# Keep this file declarative: function definitions only, with no top-level actions.

# Print section header for interactive mode
clear_screen() {
    if [ -t 1 ] && command -v clear >/dev/null 2>&1 && [ -n "${TERM:-}" ]; then
        clear >/dev/null 2>&1 || true
    fi
}

print_header() {
    local title="$1"
    echo ""
    echo "============================================================"
    echo "  $title"
    echo "============================================================"
}

# Function to run interactive guided installation
run_interactive_install() {
    clear_screen
    cat << "EOF"

                 Interactive Installation Guide
                 ===============================

EOF

    echo "Welcome! This guided installation will help you set up Vocalinux"
    echo "with the best options for your system."
    echo ""
    echo "Local engines (whisper.cpp, Whisper, Faster Whisper, VOSK) process audio on-device after you download a model."
    echo "Optional Remote API is off unless you choose it; then audio goes only to the server you configure."
    echo ""

    # Step 1: Detect and display system info
    print_header "Step 1: Your System"
    echo "Detected: $DISTRO_NAME $DISTRO_VERSION"

    # Get hardware recommendation
    local RECOMMENDATION=$(get_engine_recommendation)
    local RECOMMENDED_ENGINE=$(echo "$RECOMMENDATION" | cut -d':' -f1)
    local RECOMMENDED_ICON=$(echo "$RECOMMENDATION" | cut -d':' -f2)
    local RECOMMENDED_REASON=$(echo "$RECOMMENDATION" | cut -d':' -f3-)

    echo "Hardware: $RECOMMENDED_REASON"
    echo ""

    # Step 2: Choose speech recognition engine
    print_header "Step 2: Choose Speech Recognition Engine"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  1. WHISPER.CPP  * RECOMMENDED                              │"
    echo "  │     • Local default engine; CUDA, Vulkan, or CPU            │"
    echo "  │     • Supports NVIDIA (CUDA), AMD, Intel (Vulkan)           │"
    echo "  │     • CPU-only mode available for older systems             │"
    echo "  │     • Models: tiny (39MB) to large (1.5GB)                  │"
    echo "  │     • ~33 languages plus Auto-detect                        │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  2. WHISPER (OpenAI)                                        │"
    echo "  │     • PyTorch-based, high accuracy                          │"
    echo "  │     • Only supports NVIDIA GPUs (CUDA)                      │"
    echo "  │     • Larger download (~2GB with CUDA)                      │"
    echo "  │     • Good for development/research                         │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  3. VOSK                                                    │"
    echo "  │     • Lightweight and fast                                  │"
    echo "  │     • Works on older/low-RAM systems                        │"
    echo "  │     • ~40MB download                                        │"
    echo "  │     • Good for basic dictation needs                        │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  4. FASTER-WHISPER                                          │"
    echo "  │     • Optional CTranslate2 Whisper backend                  │"
    echo "  │     • Fast on CPU with INT8 quantization                    │"
    echo "  │     • Checksum-verified Hugging Face models                 │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  5. REMOTE API (ADVANCED)                                   │"
    echo "  │     • Offload processing to a GPU server on your network    │"
    echo "  │     • Ideal for laptops without GPU                         │"
    echo "  │     • Supports whisper.cpp server & OpenAI-compatible APIs  │"
    echo "  │     • Minimal local resources needed                        │"
    echo "  │     • Requires a remote server to be running                │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""

    # Show recommendation
    case "$RECOMMENDED_ENGINE" in
        whisper_cpp)
            echo "  → Recommendation: whisper.cpp (recommended for your hardware)"
            DEFAULT_CHOICE="1"
            ;;
        vosk)
            echo "  → Recommendation: VOSK (lightweight option for your system)"
            DEFAULT_CHOICE="3"
            ;;
        *)
            echo "  → Recommendation: whisper.cpp (recommended default)"
            DEFAULT_CHOICE="1"
            ;;
    esac
    echo ""

    read -p "Choose engine [1-5] (default: $DEFAULT_CHOICE): " ENGINE_CHOICE
    ENGINE_CHOICE=${ENGINE_CHOICE:-$DEFAULT_CHOICE}

    case "$ENGINE_CHOICE" in
        1)
            SELECTED_ENGINE="whisper_cpp"
            ENGINE_DISPLAY="Whisper.cpp (Recommended)"
            ;;
        2)
            SELECTED_ENGINE="whisper"
            ENGINE_DISPLAY="Whisper (OpenAI)"
            ;;
        3)
            SELECTED_ENGINE="vosk"
            ENGINE_DISPLAY="VOSK (Lightweight)"
            ;;
        4)
            SELECTED_ENGINE="faster_whisper"
            ENGINE_DISPLAY="Faster-Whisper"
            ;;
        5)
            SELECTED_ENGINE="remote_api"
            ENGINE_DISPLAY="Remote API"
            ;;
        *)
            SELECTED_ENGINE="whisper_cpp"
            ENGINE_DISPLAY="Whisper.cpp (Recommended)"
            ;;
    esac

    # Step 3: Whisper.cpp backend selection (if whisper.cpp chosen)
    if [[ "$SELECTED_ENGINE" == "whisper_cpp" ]]; then
        print_header "Step 3: Choose Whisper.cpp Backend"
        echo ""

        # Detect available backends
        local BACKEND_INFO=$(detect_whispercpp_backends)
        local RECOMMENDED_BACKEND=$(echo "$BACKEND_INFO" | cut -d':' -f1)
        local RECOMMENDED_REASON=$(echo "$BACKEND_INFO" | cut -d':' -f2)
        local CAN_BUILD_GPU=$(echo "$BACKEND_INFO" | cut -d':' -f3)
        local HAS_VULKAN=$(echo "$BACKEND_INFO" | cut -d':' -f4)
        local HAS_NVIDIA=$(echo "$BACKEND_INFO" | cut -d':' -f5)
        local HAS_VULKAN_DEV=$(echo "$BACKEND_INFO" | cut -d':' -f6)
        local HAS_CUDA_DEV=$(echo "$BACKEND_INFO" | cut -d':' -f7)
        local VULKAN_COMPAT=$(echo "$BACKEND_INFO" | cut -d':' -f8)
        local VULKAN_COMPAT_REASON=$(echo "$BACKEND_INFO" | cut -d':' -f9)

        # Show warning for incompatible GPUs
        if [[ "$VULKAN_COMPAT" == "incompatible" ]]; then
            echo ""
            print_warning "═══════════════════════════════════════════════════════════════"
            print_warning "  ⚠️  INCOMPATIBLE GPU DETECTED"
            print_warning "═══════════════════════════════════════════════════════════════"
            print_warning ""
            print_warning "  Your GPU: $VULKAN_COMPAT_REASON"
            print_warning ""
            print_warning "  This Intel GPU lacks VK_KHR_16bit_storage support, which is"
            print_warning "  required for whisper.cpp Vulkan acceleration."
            print_warning ""
            print_warning "  The CPU backend will be used instead, which is still fast!"
            print_warning ""
            print_warning "═══════════════════════════════════════════════════════════════"
            echo ""
        fi

        echo "Whisper.cpp can use different backends for speech recognition:"
        echo ""

        if [[ "$CAN_BUILD_GPU" == "true" ]]; then
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  1. GPU (Vulkan/CUDA)  * RECOMMENDED                        │"
            echo "  │     • Fastest performance with GPU acceleration             │"
            printf "  │     • %-*s│\n" 54 "$RECOMMENDED_REASON"
            echo "  │     • Requires building from source (takes ~2-5 min)        │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  2. CPU (Pre-built)                                         │"
            echo "  │     • Works on all systems                                  │"
            echo "  │     • Faster installation (no compilation)                  │"
            echo "  │     • Good performance on modern CPUs                       │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""
            echo "  → Recommendation: GPU backend for best performance"
            local DEFAULT_BACKEND="1"
        else
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  1. GPU (Vulkan/CUDA)                                       │"
            echo "  │     • ⚠️  GPU libraries not detected                        │"
            echo "  │     • Requires: libvulkan-dev, glslc/glslang-tools (Vulkan) │"
            echo "  │              or: CUDA toolkit (NVIDIA)                      │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  2. CPU (Pre-built)  * RECOMMENDED                          │"
            echo "  │     • Works on all systems                                  │"
            echo "  │     • Fast installation (no compilation)                    │"
            echo "  │     • Good performance on modern CPUs                       │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""

            if [[ "$HAS_VULKAN" == "yes" && "$HAS_VULKAN_DEV" != "true" ]]; then
                echo "  💡 Tip: Install 'libvulkan-dev' and a shader compiler for GPU support:"
                echo "     sudo apt install libvulkan-dev glslc 2>/dev/null || sudo apt install libvulkan-dev glslang-tools"
                echo ""
            elif [[ "$HAS_NVIDIA" == "yes" && "$HAS_CUDA_DEV" != "true" ]]; then
                echo "  💡 Tip: Install CUDA toolkit for NVIDIA GPU support:"
                echo "     https://developer.nvidia.com/cuda-downloads"
                echo ""
            fi

            echo "  → Recommendation: CPU backend (GPU libraries not detected)"
            local DEFAULT_BACKEND="2"
        fi

        read -p "Choose backend [1-2] (default: $DEFAULT_BACKEND): " BACKEND_CHOICE
        BACKEND_CHOICE=${BACKEND_CHOICE:-$DEFAULT_BACKEND}

        if [[ "$BACKEND_CHOICE" == "1" ]]; then
            WHISPERCPP_BACKEND="gpu"
            BACKEND_DISPLAY="GPU (Vulkan/CUDA)"
        else
            WHISPERCPP_BACKEND="cpu"
            BACKEND_DISPLAY="CPU (Pre-built)"
        fi

        echo ""
    fi

    # Step 3 for Remote API: Configure server URL
    if [[ "$SELECTED_ENGINE" == "remote_api" ]]; then
        print_header "Step 3: Configure Remote Server"
        echo ""
        print_info "You need a speech recognition server running on your local network."
        echo ""
        echo "  Supported servers:"
        echo "    • whisper.cpp server:  ./server -m model.bin --host 0.0.0.0 --port 8080"
        echo "    • LocalAI:            docker run -p 8080:8080 localai/localai"
        echo "    • Faster Whisper:      faster-whisper-server --host 0.0.0.0 --port 8080"
        echo "    • Any OpenAI-compatible speech API"
        echo ""
        read -p "Enter remote server URL (or leave blank to set later): " REMOTE_API_URL_INPUT
        if [ -n "$REMOTE_API_URL_INPUT" ]; then
            REMOTE_API_URL="$REMOTE_API_URL_INPUT"
            REMOTE_DISPLAY="$REMOTE_API_URL"
        else
            REMOTE_API_URL=""
            REMOTE_DISPLAY="(configure later in Settings)"
        fi
        echo ""
    fi

    # Step 4: Model download preference (skip for remote_api)
    if [[ "$SELECTED_ENGINE" != "remote_api" ]]; then
    print_header "Step 4: Model Download"
    echo ""
    echo "Speech recognition models can be downloaded now or later."
    echo ""
    echo "  1. Download now (recommended)"
    echo "     • Faster first run - ready to use immediately"
    echo "     • Offline capable right after install"
    echo ""
    echo "  2. Download later"
    echo "     • Smaller initial install"
    echo "     • Models download automatically on first use"
    echo ""

    read -p "Download models now? [1-2] (default: 1): " MODELS_CHOICE
    MODELS_CHOICE=${MODELS_CHOICE:-1}

    if [[ "$MODELS_CHOICE" == "2" ]]; then
        SKIP_MODELS="yes"
        MODELS_DISPLAY="Download on first use"
    else
        MODELS_DISPLAY="Download now (recommended)"
    fi
    else
        # Remote API: No need to download model
        SKIP_MODELS="yes"
        MODELS_DISPLAY="Not needed (remote processing)"
    fi

    # Summary
    print_header "Installation Summary"
    echo ""
    echo "  Speech Engine: $ENGINE_DISPLAY"
    if [[ "$SELECTED_ENGINE" == "whisper_cpp" ]]; then
        echo "  Backend: ${BACKEND_DISPLAY:-CPU (Pre-built)}"
        if [[ "${WHISPERCPP_BACKEND}" == "gpu" ]]; then
            echo "  Note: GPU build will compile from source (2-5 minutes)"
        fi
    fi
    if [[ "$SELECTED_ENGINE" == "remote_api" ]]; then
        echo "  Remote Server: $REMOTE_DISPLAY"
    fi
    echo "  Models: $MODELS_DISPLAY"
    echo "  Install Location: ${INSTALL_DIR:-\$HOME/.local/share/vocalinux}"
    echo ""
    read -p "Press Enter to continue with installation, or Ctrl+C to cancel..."
    echo ""
}
