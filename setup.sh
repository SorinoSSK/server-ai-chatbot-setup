#!/bin/bash
set -euo pipefail

# ======================================== #
# IMPORT DEPENDENCIES START
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

FILES_TO_IMPORT=(
"${SCRIPT_DIR}/telegram_gateway/setup.sh"
)

for FILE_TO_IMPORT in "${FILES_TO_IMPORT[@]}"; do
    if [[ ! -f "${FILE_TO_IMPORT}" ]]; then
        echo "SYSTEM ERROR: ${FILE_TO_IMPORT} not found"
        exit 1
    else
        source "${FILE_TO_IMPORT}"
    fi
done
# IMPORT DEPENDENCIES END
# ======================================== #
# *
# ======================================== #
# Config Management Functions Start

# List of config.ini variable names treated as sensitive - masked when
# generating config_sample.ini, and prompted for individually when
# generating config.ini from config_sample.ini. Expand by adding another
# echo line here.
get_masked_config_variables()
{
    echo "CHATBOT_RABBITMQ_USERNAME"
    echo "CHATBOT_RABBITMQ_PASSWORD"
    echo "CHATBOT_TELEGRAM_BOT_TOKEN"
    echo "CHATBOT_TELEGRAM_ALLOWED_CHAT_IDS"
    echo "CHATBOT_REDIS_USERNAME"
    echo "CHATBOT_REDIS_PASSWORD"
}

generate_config_sample()
{
    if [[ ! -f ./config.ini ]]; then
        echo "SYSTEM ERROR: config.ini not found."
        return 1
    fi

    cp ./config.ini ./config_sample.ini

    local variable_name
    while IFS= read -r variable_name; do
        if grep -q "^${variable_name}=" ./config_sample.ini; then
            sed -i "s|^${variable_name}=.*|${variable_name}=\"REPLACE_WITH_${variable_name}\"|" ./config_sample.ini
        fi
    done < <(get_masked_config_variables)

    echo "SYSTEM: config_sample.ini generated - safe to commit, config.ini is not."
}

prompt_config_from_sample()
{
    if [[ ! -f ./config_sample.ini ]]; then
        echo "SYSTEM ERROR: config_sample.ini not found. Generate it first (option 6)."
        return 1
    fi

    cp ./config_sample.ini ./config.ini

    local variable_name
    local user_input
    while IFS= read -r variable_name; do
        if grep -q "^${variable_name}=\"REPLACE_WITH_${variable_name}\"" ./config.ini; then
            if [[ "${variable_name}" == "CHATBOT_TELEGRAM_ALLOWED_CHAT_IDS" ]]; then
                read -rp "Enter value for ${variable_name} (comma-separated chat IDs): " user_input
            else
                read -rp "Enter value for ${variable_name}: " user_input
            fi
            sed -i "s|^${variable_name}=.*|${variable_name}=\"${user_input}\"|" ./config.ini
        fi
    done < <(get_masked_config_variables)

    echo "SYSTEM: config.ini generated from config_sample.ini."
}

# Config Management Functions End
# ======================================== #
# *
# ======================================== #
# Development Functions Start

build_telegram_gateway_dev_image()
{
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local dev_path="${script_dir}/${CHATBOT_TELEGRAM_GATEWAY_PATH_NAME}"
    echo "Associated path: ${dev_path}"
    current_dir="$(pwd)"
    cd "${dev_path}"
    tg_dev_build_docker
    cd "${current_dir}"
}

build_all_dev_images()
{
    build_telegram_gateway_dev_image
}

create_redis_data_path()
{
    mkdir -p "${CHATBOT_REDIS_DATA_PATH}"
}

run_dev()
{
    cp ./config.ini ./.env
    tg_dev_remove_docker
    create_redis_data_path
    docker compose -f compose.dev.yml up -d
}

stop_dev()
{
    docker compose -f compose.dev.yml down --volumes
}

# Development Functions End
# ======================================== #
# *
# ======================================== #
# Production Functions Start

build_telegram_gateway_prod_image()
{
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local dev_path="${script_dir}/${CHATBOT_TELEGRAM_GATEWAY_PATH_NAME}"
    echo "Associated path: ${dev_path}"
    current_dir="$(pwd)"
    cd "${dev_path}"
    tg_prod_build_docker
    cd "${current_dir}"
}

build_all_prod_images()
{
    build_telegram_gateway_prod_image
}

# Production Functions End
# ======================================== #

setup_show_menu()
{
    echo "Select an option:"
    echo "[1] Build Docker Images (Dev)"
    echo "[2] Build Docker Images (Prod)"
    echo "[3] Run Docker Compose (Dev)"
    echo "[4] Stop Docker Compose (Dev)"
    echo "[5] Clear all docker's volume"
    echo "[6] Generate config_sample.ini (mask sensitive variables)"
    echo "[7] Generate config.ini from config_sample.ini (prompts for values)"
    echo "[Q] Quit"
    local setup_select
    read -rp "Select Task: " setup_select

    case "${setup_select}" in
    1)
        build_all_dev_images
        ;;
    2)
        build_all_prod_images
        ;;
    3)
        run_dev
        ;;
    4)
        stop_dev
        ;;
    5)
        docker volume rm $(docker volume ls -q)
        ;;
    6)
        generate_config_sample
        ;;
    7)
        prompt_config_from_sample
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
    config_path="./config.ini"
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo "NOTICE: ${script_dir}"

    if [[ -f "${config_path}" ]]; then
        source "${config_path}"
    else
        echo "NOTICE: ${config_path} not found."
        prompt_config_from_sample
        source "${config_path}"
    fi

    setup_show_menu
fi
