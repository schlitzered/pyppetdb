from fastapi import Request


async def some_endpoint(request: Request):
    # Access the client certificate from the ASGI scope
    client_cert = request.scope.get("client")

    if client_cert:
        # The client cert info is in the scope under 'peercert'
        peercert = request.scope.get("peercert")

        if peercert:
            # Extract the CN from the subject
            subject = peercert.get("subject", ())
            for rdn in subject:
                for name, value in rdn:
                    if name == "commonName":
                        cn = value
                        break
