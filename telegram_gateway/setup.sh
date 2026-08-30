#!/bin/bash
set -euo pipefail

docker_check()
{
    local target_container="${1:-}"
    if docker inspect "${target_container}" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

stop_docker()
{
    target_container="${1:-}"
    if docker inspect "$target_container" >/dev/null 2>&1; then
        status=$(docker inspect -f '{{.State.Status}}' "$target_container")

        if [[ "$status" == "running" || "$status" == "restarting" ]]; then
            echo "SYSTEM: $target_container stopping..."
            docker stop "$target_container"

            attempts=0
            max_attempts=60
            while (( attempts < max_attempts )); do
                current_state=$(docker inspect -f '{{.State.Status}}' "$target_container")
                [[ "$current_state" == "exited" ]] && break
                sleep 2
                ((attempts++))
            done

            echo "SYSTEM: $target_container stopped."
        fi
    else
        echo "Skip: Docker container $target_container do not exist."
    fi
}

docker_network_check()
{
    if docker network inspect "${CHATBOT_NETWORK_NAME}" >/dev/null 2>&1; then
        echo "Network '${CHATBOT_NETWORK_NAME}' already exists."
    else
        docker network create "${CHATBOT_NETWORK_NAME}"
        echo "Created network '${CHATBOT_NETWORK_NAME}'"
    fi
}

tg_prod_build_docker()
{
    # Docker to build all from <project>/telegram_gateway
    docker build -f Dockerfile.prod -t "${CHATBOT_TELEGRAM_GATEWAY_PROD_IMAGE_NAME}:${CHATBOT_TELEGRAM_GATEWAY_PROD_VERSION}" .
}

tg_dev_build_docker()
{
    # Docker to build all from <project>/telegram_gateway
    docker build -f Dockerfile.dev -t "${CHATBOT_TELEGRAM_GATEWAY_DEV_IMAGE_NAME}" .
}

tg_dev_run_docker()
{
    local dev_path="${1:-}"
    tg_dev_remove_docker
    docker_network_check
    # Port publishing disabled for now. To re-enable, add back:
    #   -p "${CHATBOT_TELEGRAM_GATEWAY_DEV_PORT}:${CHATBOT_TELEGRAM_GATEWAY_DEV_PORT}" \
    if [[ -n "${dev_path}" ]]; then
        echo "Exposed telegram_gateway_application."
        docker run -d \
            --name "${CHATBOT_TELEGRAM_GATEWAY_DEV_CONTAINER_NAME}" \
            --network "${CHATBOT_NETWORK_NAME}" \
            -e "TELEGRAM_BOT_TOKEN=${CHATBOT_TELEGRAM_BOT_TOKEN}" \
            -e "TELEGRAM_ALLOWED_CHAT_IDS=${CHATBOT_TELEGRAM_ALLOWED_CHAT_IDS}" \
            -v "${dev_path}/telegram_gateway_application:/telegram_gateway/telegram_gateway_application" \
            "${CHATBOT_TELEGRAM_GATEWAY_DEV_IMAGE_NAME}"
    else
        docker run -d \
            --name "${CHATBOT_TELEGRAM_GATEWAY_DEV_CONTAINER_NAME}" \
            --network "${CHATBOT_NETWORK_NAME}" \
            -e "TELEGRAM_BOT_TOKEN=${CHATBOT_TELEGRAM_BOT_TOKEN}" \
            -e "TELEGRAM_ALLOWED_CHAT_IDS=${CHATBOT_TELEGRAM_ALLOWED_CHAT_IDS}" \
            "${CHATBOT_TELEGRAM_GATEWAY_DEV_IMAGE_NAME}"
    fi
}

tg_dev_remove_docker()
{
    stop_docker "${CHATBOT_TELEGRAM_GATEWAY_DEV_CONTAINER_NAME}"
    if docker_check "${CHATBOT_TELEGRAM_GATEWAY_DEV_CONTAINER_NAME}"; then
        docker rm "${CHATBOT_TELEGRAM_GATEWAY_DEV_CONTAINER_NAME}"
    fi
}

tg_dev_access_docker()
{
    docker exec -it "${CHATBOT_TELEGRAM_GATEWAY_DEV_CONTAINER_NAME}" sh
}

tg_dev_show_menu()
{
    local dev_path="${1:-}"
    echo "Select an option:"
    echo "[1] Build Docker Image and Run Container"
    echo "[2] Remove Docker Container"
    echo "[3] Access Docker Container Shell"
    echo "[Q] Quit"
    local setup_select
    read -rp "Select Task: " setup_select

    case "${setup_select}" in
    1)
        tg_dev_build_docker
        tg_dev_run_docker "${dev_path}"
        ;;
    2)
        tg_dev_remove_docker
        ;;
    3)
        tg_dev_access_docker
        ;;
    q|Q)
        exit 0
        ;;
    *)
        echo "Invalid selection.."
        exit 1
        ;;
    esac
}

# DISPLAY MENU ONLY FOR DIRECT EXECUTION.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    config_path="../config.ini"
    if [[ -f "${config_path}" ]]; then
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        echo "NOTICE: ${script_dir}"

        source "${config_path}"
        tg_dev_show_menu "${script_dir}"
    else
        echo "NOTICE: ${config_path} not found."
    fi
fi
