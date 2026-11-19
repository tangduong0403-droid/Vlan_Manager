from modules.validator import validate_yaml_files
from dotenv import load_dotenv
from core.deployment_manager import DeploymentManager


def print_menu():
    print("\n==================================================")
    print("   MULTI-VENDOR NETWORK AUTOMATION SYSTEM")
    print("                 VLAN MANAGER")
    print("==================================================")
    print("[1] Deploy Configuration (Concurrent)")
    print("[2] Backup Configuration")
    print("[3] Compare Configuration (Diff)")
    print("[4] Rollback Configuration")
    print("[5] Dry-run (Preview Commands)")
    print("[6] Compliance Checking")
    print("[7] Network Device Status & Facts (OS/CPU/RAM/ARP/MAC)")
    print("[8] Export Summary Report (CSV)")
    print("[9] Port Utilization Report (Thống kê cổng & Xuất CSV)")
    print("[0] Exit")
    print("==================================================")


def main():
    load_dotenv()
    manager = DeploymentManager()

    while True:
        print_menu()
        choice = input("Select an option: ").strip()
        if choice in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            if not validate_yaml_files():
                continue
        if choice == "1":
            manager.execute_deploy()
        elif choice == "2":
            manager.execute_backup()
        elif choice == "3":
            manager.execute_diff()
        elif choice == "4":
            manager.execute_rollback()
        elif choice == "5":
            manager.execute_dry_run()
        elif choice == "6":
            manager.execute_compliance()
        elif choice == "7":
            manager.execute_status()
        elif choice == "8":
            manager.execute_report()
        elif choice == "9":
            manager.execute_port_report()
        elif choice == "0":
            print("Exiting VLAN Manager. Goodbye!")
            break
        else:
            print("Lựa chọn không hợp lệ. Vui lòng nhập số từ 0 đến 9.")


if __name__ == "__main__":
    main()