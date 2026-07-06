package it.osint.raven.dto.source;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Authentication settings for an OSINT source. Secret values are write-only in API documentation.")
public class AuthenticationDto {

    @JsonProperty("type")
    @Schema(description = "Authentication mechanism used by the source.", example = "BEARER_TOKEN")
    private AuthenticationType type;

    @JsonProperty("username")
    @Schema(description = "Username for basic or custom authentication.", example = "collector")
    private String username;

    @JsonProperty("password")
    @Schema(description = "Password for basic authentication.", accessMode = Schema.AccessMode.WRITE_ONLY)
    private String password;

    @JsonProperty("api_key")
    @Schema(description = "API key used by the source.", accessMode = Schema.AccessMode.WRITE_ONLY)
    private String apiKey;

    @JsonProperty("bearer_token")
    @Schema(description = "Bearer token used by the source.", accessMode = Schema.AccessMode.WRITE_ONLY)
    private String bearerToken;
}
