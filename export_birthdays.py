from app import get_services, get_birthdays, get_additional_events, write_birthdays_file


def export_to_file(filename: str = "Geburtstage.txt") -> None:
    """Fetch birthdays from Google People API and write them sorted to a file."""
    people_service, _, auth_url = get_services()
    if auth_url:
        print("Öffne den folgenden Link im Browser und autorisiere den Zugriff:")
        print(auth_url)
        code = input("Gib den angezeigten Code ein: ")
        people_service, _, _ = get_services(auth_code=code)

    birthdays = get_birthdays(people_service)
    extras = get_additional_events(people_service)
    all_events = birthdays + extras
    write_birthdays_file(all_events, filename)


if __name__ == "__main__":
    export_to_file()
