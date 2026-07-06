package it.osint.raven.exceptions;

public class ConfigurationUpdateException extends RuntimeException {

    public ConfigurationUpdateException(String message, Throwable cause) {
        super(message, cause);
    }
}
