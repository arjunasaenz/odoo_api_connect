def migrate(cr, version):
    cr.execute(
        "UPDATE api_connect_event "
        "SET state = 'no_employee' "
        "WHERE state = 'unmatched' AND employee_id IS NULL"
    )
    cr.execute(
        "UPDATE api_connect_event "
        "SET state = 'stale', "
        "    note = 'Marcación descartada (histórico): su hora era anterior al turno abierto en curso.' "
        "WHERE state = 'unmatched'"
    )
