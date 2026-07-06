package it.osint.raven.controlleradvices;

import it.osint.raven.dto.system.ApiErrorResponse;
import it.osint.raven.exceptions.ConfigurationUpdateException;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.Instant;

@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(ConfigurationUpdateException.class)
    public ResponseEntity<ApiErrorResponse> handleConfigurationUpdate(
            ConfigurationUpdateException exception,
            HttpServletRequest request
    ) {
        log.error("Unable to update configuration for path {}", request.getRequestURI(), exception);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(new ApiErrorResponse(
                        "CONFIGURATION_SAVE_FAILED",
                        exception.getMessage(),
                        request.getRequestURI(),
                        Instant.now()
                ));
    }
}
