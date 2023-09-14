package drift

default allow = false

allow {
    input.method = "POST"
    input.path = ["auth"]
}

allow {
    input.method = "GET"
    input.path = ["clients"]
}
