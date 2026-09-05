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

bo_prod_build_docker()
{
    # Docker to build all from <project>/bot_orchestrator
    docker build -f Dockerfile.prod -t "${CHATBOT_BOT_ORCHESTRATOR_PROD_IMAGE_NAME}:${CHATBOT_BOT_ORCHESTRATOR_PROD_VERSION}" .
}

bo_dev_build_docker()
{
    # Docker to build all from <project>/bot_orchestrator
    docker build -f Dockerfile.dev -t "${CHATBOT_BOT_ORCHESTRATOR_DEV_IMAGE_NAME}" .
}

bo_dev_run_docker()
{
    local dev_path="${1:-}"
    bo_dev_remove_docker
    docker_network_check
    if [[ -n "${dev_path}" ]]; then
        echo "Exposed bot_orchestrator_application."
        docker run -d \
            --name "${CHATBOT_BOT_ORCHESTRATOR_DEV_CONTAINER_NAME}" \
            --network "${CHATBOT_NETWORK_NAME}" \
            -e "Q_USER=${CHATBOT_RABBITMQ_USERNAME}" \
            -e "Q_PASSWORD=${CHATBOT_RABBITMQ_PASSWORD}" \
            -v "${dev_path}/bot_orchestrator_application:/bot_orchestrator/bot_orchestrator_application" \
            "${CHATBOT_BOT_ORCHESTRATOR_DEV_IMAGE_NAME}"
    else
        docker run -d \
            --name "${CHATBOT_BOT_ORCHESTRATOR_DEV_CONTAINER_NAME}" \
            --network "${CHATBOT_NETWORK_NAME}" \
            -e "Q_USER=${CHATBOT_RABBITMQ_USERNAME}" \
            -e "Q_PASSWORD=${CHATBOT_RABBITMQ_PASSWORD}" \
            "${CHATBOT_BOT_ORCHESTRATOR_DEV_IMAGE_NAME}"
    fi
}

bo_dev_remove_docker()
{
    stop_docker "${CHATBOT_BOT_ORCHESTRATOR_DEV_CONTAINER_NAME}"
    if docker_check "${CHATBOT_BOT_ORCHESTRATOR_DEV_CONTAINER_NAME}"; then
        docker rm "${CHATBOT_BOT_ORCHESTRATOR_DEV_CONTAINER_NAME}"
    fi
}

bo_dev_access_docker()
{
    docker exec -it "${CHATBOT_BOT_ORCHESTRATOR_DEV_CONTAINER_NAME}" sh
}

bo_dev_show_menu()
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
        bo_dev_build_docker
        bo_dev_run_docker "${dev_path}"
        ;;
    2)
        bo_dev_remove_docker
        ;;
    3)
        bo_dev_access_docker
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
        bo_dev_show_menu "${script_dir}"
    else
        echo "NOTICE: ${config_path} not found."
    fi
fi
